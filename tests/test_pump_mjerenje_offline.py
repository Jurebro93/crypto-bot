"""25.11. (vlasnik: „mjerenje da”, jednokratno 48 h, besplatno): live/pumpmjerenje.py, offline (bez mreže).

  - prekidač PUMP_MJERENJE_DO: zadano isključeno, rok u budućnosti (do 72 h) uključuje, prošao / predaleko / smeće ne
  - live: subscribeNewToken samo dok mjerenje traje (i uz fokus midcap); bez mjerenja fokus kao dosad; nakon roka
    unsubscribeNewToken i ništa se više ne bilježi
  - lansiranja iz mjerenja (fokus uključen) nikad ne ulaze u live_launches; nijedan drugi modul ne čita mjerenje
  - razredi deva (24 h broj, vlastita kupnja, „nepoznat dev, bez kupnje, prvi token”), procjena naknade, gornjih 1 %
  - strop redaka; DexScreener serije po 30, uzorak se smanjuje kad bi zahtjeva bilo previše, ništa nakon roka;
    završni sažetak jednom; baza obrisana 7 dana nakon roka

    python3 -m unittest tests.test_pump_mjerenje_offline
"""
import asyncio
import json
import os
import re
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from live import pumpmjerenje as pm, pumpportal, store as lstore  # noqa: E402

NOW = 1_790_000_000


def create(mint, dev, sol=0.0, mcap=28.0):
    return {"signature": "s" + mint, "mint": mint, "traderPublicKey": dev, "txType": "create", "initialBuy": sol * 3e7,
            "solAmount": sol, "marketCapSol": mcap, "name": "N", "symbol": "S", "pool": "pump"}


def pair(mint, vol=None, mcap=5000.0, dex="pumpfun", quote=pm.WSOL, pc=None, tx=(3, 1)):
    p = {"baseToken": {"address": mint}, "quoteToken": {"address": quote}, "dexId": dex,
         "priceUsd": "0.000002", "priceNative": "0.00000002", "marketCap": mcap, "fdv": mcap,
         "txns": {"h24": {"buys": tx[0], "sells": tx[1]}}, "priceChange": pc or {}}
    p["volume"] = {"h24": vol} if vol is not None else {}
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "pump_mjerenje.db")
        p = mock.patch.dict(os.environ, {"PUMP_MJERENJE_DB": self.db})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop(pm.ENV, None)
        self.logs = []

    def log(self, s):
        self.logs.append(s)


class Switch(Base):
    def test_default_off_and_expiry(self):
        self.assertFalse(pm.active(NOW, {}))
        self.assertEqual(pm.deadline({}), 0)
        self.assertTrue(pm.active(NOW, {pm.ENV: str(NOW + 48 * 3600)}))
        self.assertFalse(pm.active(NOW, {pm.ENV: str(NOW - 1)}))              # prošao
        self.assertFalse(pm.active(NOW, {pm.ENV: str(NOW + 80 * 3600)}))      # predaleko: greška u upisu
        self.assertFalse(pm.active(NOW, {pm.ENV: "sutra"}))
        self.assertIsNone(pm.Biljeznik.iz_okoline(env={}, now=NOW))
        self.assertIsNotNone(pm.Biljeznik.iz_okoline(env={pm.ENV: str(NOW + 3600)}, now=NOW))

    def test_tick_without_switch_does_nothing(self):
        calls = []
        self.assertEqual(pm.tick(NOW, fetch=lambda m: calls.append(m) or [], log=self.log, env={}), 0)
        self.assertFalse(os.path.exists(self.db))
        self.assertEqual((calls, self.logs), ([], []))


class Live(Base):
    """pumpportal.run with a fake socket and a fake clock."""

    def run_feed(self, fokus, deadline, msgs, clock_step=1.0, steps=8):
        sent = []
        queue = list(msgs)
        t = [float(NOW)]

        class WS:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def send(self, m):
                sent.append(json.loads(m))

            async def recv(self):
                await asyncio.sleep(0)
                t[0] += clock_step
                return json.dumps(queue.pop(0)) if queue else "{}"

        stops = iter([False] * (steps + 1) + [True] * 10)
        env = {"FOKUS_MIDCAP_FORCE": "1" if fokus else "0"}
        if deadline:
            env[pm.ENV] = str(deadline)
        fake = types.SimpleNamespace(connect=lambda *a, **k: WS())
        con = lstore.connect(os.path.join(self.tmp.name, "hype.db"))
        self.addCleanup(con.close)
        with mock.patch.dict(sys.modules, {"websockets": fake}), mock.patch.dict(os.environ, env), \
                mock.patch.object(pumpportal, "wanted", lambda fokus=None, **k: (["HELD"], ["FOLLOWED"], {"HELD"})), \
                mock.patch("live.pulse.check_dumps", lambda *a, **k: None), \
                mock.patch("time.time", lambda: t[0]):
            asyncio.run(pumpportal.run(con, log=self.log, new_tokens=True, migrations=True, stop=lambda: next(stops)))
        launches = [r[0] for r in con.execute("SELECT mint FROM live_launches")]
        mj = []
        if os.path.exists(self.db):
            c = sqlite3.connect(self.db)
            mj = [r[0] for r in c.execute("SELECT mint FROM launches ORDER BY ts")]
            c.close()
        return [m.get("method") for m in sent], launches, mj

    def test_fokus_without_measurement_unchanged(self):
        methods, launches, mj = self.run_feed(True, None, [create("M1", "D1")])
        self.assertNotIn("subscribeNewToken", methods)
        self.assertNotIn("subscribeMigration", methods)
        # nothing subscribed, so nothing arrives in reality; the fake socket's message takes the old path exactly
        self.assertEqual((launches, mj), (["M1"], []))
        self.assertFalse(os.path.exists(self.db))

    def test_fokus_with_measurement_only_own_db(self):
        methods, launches, mj = self.run_feed(True, NOW + 48 * 3600, [create("M1", "D1"), create("M2", "D1", 0.5)])
        self.assertIn("subscribeNewToken", methods)
        self.assertNotIn("subscribeMigration", methods)   # fokus: migracije i dalje isključene
        self.assertEqual(launches, [])                     # nikad u live_launches (skener, precall, teme, učenje)
        self.assertEqual(mj, ["M1", "M2"])
        self.assertTrue(any(x.startswith("pump mjerenje: uključeno do") for x in self.logs))

    def test_no_fokus_with_measurement_both(self):
        methods, launches, mj = self.run_feed(False, NOW + 48 * 3600, [create("M1", "D1")])
        self.assertEqual(methods.count("subscribeNewToken"), 1)
        self.assertEqual((launches, mj), (["M1"], ["M1"]))

    def test_deadline_passes_on_open_connection(self):
        msgs = [create("M1", "D1"), create("M2", "D2")] + [{}] * 3 + [create("M9", "D9")]
        methods, launches, mj = self.run_feed(True, NOW + 3, msgs, clock_step=1.0, steps=10)
        self.assertIn("unsubscribeNewToken", methods)
        self.assertNotIn("M9", mj)
        self.assertEqual(launches, [])
        self.assertTrue(any("rok istekao" in x for x in self.logs))


class Classes(Base):
    def setUp(self):
        super().setUp()
        self.b = pm.Biljeznik(NOW + 48 * 3600, path=self.db, log=self.log)

    def feed(self, rows):
        for ts, msg in rows:
            self.b.take(msg, ts)
        self.b.flush(force=True)

    def test_dev_count_and_fee(self):
        self.feed([(NOW, create("A1", "DEVA")), (NOW + 60, create("A2", "DEVA", 1.0)),
                   (NOW + 90000, create("A3", "DEVA")),          # više od 24 h nakon A1 i A2: opet prvi
                   (NOW + 100, create("B1", "DEVB", 3.0))])
        con = sqlite3.connect(self.db)
        dev = dict(con.execute("SELECT mint, dev_24h FROM launches"))
        self.assertEqual(dev, {"A1": 1, "A2": 2, "A3": 1, "B1": 1})
        hist = dict(con.execute("SELECT mint, hist_s FROM launches"))
        self.assertEqual(hist["A3"], 90000)
        # ishod: A1 1000 $ prometa, A2 nepoznat DexScreeneru, A3 0 $, B1 100k $ i migrirao
        con.executemany("INSERT INTO ishod VALUES (?,?,?,?,?,?,?,?,?,?)", [
            ("A1", 12, NOW, 1, 1000.0, 10, 6000.0, 12000.0, 0, 100.0),
            ("A2", 12, NOW, 0, None, None, None, None, None, 100.0),
            ("A3", 12, NOW, 1, 0.0, 0, 2000.0, 2000.0, 0, 100.0),
            ("B1", 12, NOW, 1, 100000.0, 900, 150000.0, 150000.0, 1, 100.0)])
        con.commit()
        s = pm.sazetak(con, NOW + 200000, final=True)
        r = {x["razred"]: x for x in s["razredi"]}
        self.assertAlmostEqual(r["svi"]["ukupno_sol"], (1000 + 100000) * 0.003 / 100)
        self.assertEqual(r["svi"]["n"], 4)
        self.assertEqual(r["svi"]["nepoznato"], 1)
        self.assertAlmostEqual(r["svi"]["iznad"][10_000], 0.5)   # A1 (najviše viđeno 12k) i B1
        self.assertAlmostEqual(r["svi"]["iznad"][100_000], 0.25)
        self.assertAlmostEqual(r["svi"]["gornjih_1_posto"], 100000 / 101000)
        self.assertEqual(r[pm.SPECIAL]["n"], 2)                   # A1, A3: prvi u 24 h, bez kupnje
        self.assertTrue(r[pm.SPECIAL]["premalo"])
        self.assertEqual(r[pm.SPECIAL + " (puna 24 h povijest)"]["n"], 1)   # samo A3
        self.assertEqual(r["tokena deva u 24 h: 2–9"]["n"], 1)
        o = r[pm.OSTAVLJEN]                                       # A1, A3: bez kupnje i nisu bondani (B1 je bondan,
        self.assertEqual(o["n"], 2)                               # A2 ima vlastitu kupnju)
        self.assertAlmostEqual(o["prosjek_sol"], 1000 * 0.003 / 100 / 2)
        self.assertEqual(o["migrirao"], 0)
        self.assertEqual(r[pm.OSTAVLJEN + ", tokena deva u 24 h: 1 (prvi u 24 h)"]["n"], 2)
        self.assertIn(pm.OSTAVLJEN, pm.line(s))
        self.assertEqual(r["vlastita kupnja: iznad 2 SOL"]["n"], 1)
        line = pm.line(s)
        self.assertTrue(line.startswith("pump mjerenje (završno): 4 lansiranja"))
        self.assertIn("prema objavi, neprovjereno", line)
        for txt in [line] + [" ".join(x) for x in pm.table_rows(s)]:
            self.assertNotIn("DEVA", txt)
            self.assertNotIn("DEVB", txt)
        con.close()

    def test_row_cap(self):
        with mock.patch.object(pm, "MAX_ROWS", 3):
            self.feed([(NOW + i, create(f"M{i}", f"D{i}")) for i in range(5)])
            self.b.take(create("X", "Y"), NOW + 10)
            self.b.flush(force=True)
            self.assertTrue(self.b.take(create("Z", "Y"), NOW + 11) is False)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM launches").fetchone()[0], 3)
        self.assertTrue(any("strop dosegnut" in x for x in self.logs))
        con.close()

    def test_aggregate(self):
        res, sol = pm.aggregate([pair("A", 100.0, 5000.0, pc={"h1": -50}), pair("A", 50.0, 9000.0, dex="pumpswap"),
                                 pair("B", None, 3000.0, quote="OTHER")], ["A", "B", "C"])
        self.assertEqual(res["A"][:3], (1, 150.0, 8))
        self.assertEqual(res["A"][3], 9000.0)
        self.assertEqual(res["A"][4], 10000.0)    # 5000 / (1 - 0,5): vrijednost prije 1 h
        self.assertEqual(res["A"][5], 1)          # migrirao (PumpSwap par)
        self.assertEqual(res["B"][0], 2)          # zna ga, ali bez USD prometa
        self.assertEqual(res["C"][0], 0)          # nepoznat
        self.assertAlmostEqual(sol, 100.0)


class Outcome(Base):
    def seed(self, n, dl, start=NOW):
        b = pm.Biljeznik(dl, path=self.db, log=self.log)
        for i in range(n):
            b.take(create(f"T{i:05d}", f"D{i % 7}"), start + i)
        b.flush(force=True)
        b.close()

    def test_batches_checkpoints_and_end(self):
        dl = NOW + 48 * 3600
        self.seed(70, dl)
        env = {pm.ENV: str(dl)}
        calls = []

        def fetch(mints):
            calls.append(list(mints))
            return [pair(m, 10.0) for m in mints[::2]]
        pm.tick(NOW + 1800, fetch=fetch, log=self.log, env=env)     # +30 min: ništa nije dospjelo
        self.assertEqual(calls, [])
        pm.tick(NOW + 3700, fetch=fetch, log=self.log, env=env)     # +1 h za prve
        self.assertTrue(calls and all(len(c) <= 30 for c in calls))
        self.assertTrue(any(x.startswith("pump mjerenje: 70 lansiranja") for x in self.logs))
        n1 = len(calls)
        pm.tick(NOW + 12 * 3600 + 100, fetch=fetch, log=self.log, env=env)
        con = sqlite3.connect(self.db)
        ks = dict(con.execute("SELECT k, COUNT(*) FROM ishod WHERE found >= 0 GROUP BY k"))
        self.assertEqual(ks, {1: 70, 12: 70})
        self.assertEqual(con.execute("SELECT COUNT(*) FROM ishod WHERE found = 0").fetchone()[0], 70)   # pola nepoznato
        con.close()
        self.assertGreater(len(calls), n1)
        # nakon roka: nema upita, završni sažetak jednom
        calls.clear()
        self.logs.clear()
        pm.tick(dl + 10, fetch=fetch, log=self.log, env=env)
        pm.tick(dl + 700, fetch=fetch, log=self.log, env=env)
        self.assertEqual(calls, [])
        self.assertEqual(sum(1 for x in self.logs if x.startswith("pump mjerenje (završno)")), 1)
        s = pm.report(dl + 800, path=self.db)
        self.assertTrue(s["final"])
        self.assertEqual(s["s_ishodom"], 70)
        # 7 dana nakon roka: baza obrisana (i bez varijable)
        pm.tick(dl + pm.KEEP_AFTER_S + 1, fetch=fetch, log=self.log, env={})
        self.assertFalse(os.path.exists(self.db))
        self.assertEqual(calls, [])

    def test_missed_checkpoint(self):
        dl = NOW + 48 * 3600
        self.seed(5, dl)
        pm.tick(NOW + 4 * 3600, fetch=lambda m: [], log=self.log, env={pm.ENV: str(dl)})
        con = sqlite3.connect(self.db)
        self.assertEqual(dict(con.execute("SELECT k, MIN(found) FROM ishod GROUP BY k")), {1: -1})
        con.close()

    def test_sampling_shrinks_with_budget(self):
        dl = NOW + 48 * 3600
        self.seed(600, dl)   # 600 u 6 h → 2400 dnevno → 160 zahtjeva dnevno
        calls = []
        with mock.patch.object(pm, "DEX_DAY", 40), mock.patch.object(pm, "DEX_PASS", 5):
            pm.tick(NOW + 3700, fetch=lambda m: calls.append(m) or [], log=self.log, env={pm.ENV: str(dl)})
        con = sqlite3.connect(self.db)
        rate = float(pm.get(con, "udio"))
        self.assertLess(rate, 0.3)
        self.assertLessEqual(len(calls), 5)
        sampled = [m for c in calls for m in c]
        self.assertTrue(all(pm.u_of(m) < rate for m in sampled))
        self.assertTrue(any("uzorak 100" in x for x in self.logs))
        con.close()


class Isolation(unittest.TestCase):
    def test_nothing_else_reads_the_measurement(self):
        allowed = {os.path.join("live", "pumpmjerenje.py"), os.path.join("live", "pumpportal.py"),
                   os.path.join("report", "collect.py"), os.path.join("report", "render.py"),
                   os.path.join("ops", "cpuguard.py")}   # cpuguard: only the process name for the CPU guard
        bad = []
        for d, _sub, files in os.walk(ROOT):
            rel = os.path.relpath(d, ROOT)
            if rel.startswith((".git", "tests", ".cache")):
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.normpath(os.path.join(rel, f))
                if p in allowed:
                    continue
                try:
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        txt = fh.read()
                except (OSError, UnicodeDecodeError):
                    continue
                if re.search(r"pumpmjerenje|pump_mjerenje", txt):
                    bad.append(p)
        self.assertEqual(bad, [])

    def test_report_section_without_addresses(self):
        from report import render
        s = {"final": False, "rok": NOW, "lansiranja": 10, "udio": 1.0, "s_ishodom": 0, "razredi": [],
             "dex_dnevno": 5, "mb": 0.1, "izvor": pm.SLUZBENI_URL}
        html = render.pump_mjerenje_section(s)
        self.assertIn("NEPROVJERENO", html)
        self.assertIn("Mjerenje: naknada devu na pump.fun", html)


if __name__ == "__main__":
    unittest.main()
