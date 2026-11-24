"""market/trziste.py (20.11.): the BTC day colour (point in time), Fear & Greed classes, the tagging of jumps and drops,
the per-state tables, the out-of-sample split, the page on an empty and a synthetic database, the one-time council
proposal and the MCP tool. No network, no wall clock (NOW is injected)."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market import store, trziste as T  # noqa: E402
from tests import trziste_fixture as F  # noqa: E402

D = 86400


def _closes(vals, start=1_700_000_000 // D * D):
    return {start + i * D: v for i, v in enumerate(vals)}


class DayColour(unittest.TestCase):
    def test_rule(self):
        self.assertEqual(T.colour_rule(0.03, 101, 100), "zeleno")
        self.assertEqual(T.colour_rule(0.05, 99, 100), "zuto")        # up, but under its average
        self.assertEqual(T.colour_rule(-0.03, 99, 100), "crveno")
        self.assertEqual(T.colour_rule(-0.05, 101, 100), "zuto")      # down, but above its average
        self.assertEqual(T.colour_rule(0.01, 99, 100), "zuto")
        self.assertIsNone(T.colour_rule(None, 99, 100))

    def test_rising_flat_falling(self):
        up = T.colours(_closes([100 * 1.01 ** i for i in range(20)]))
        self.assertEqual(up[max(up)]["boja"], "zeleno")
        flat = T.colours(_closes([100] * 20))
        self.assertEqual(flat[max(flat)]["boja"], "zuto")
        down = T.colours(_closes([100 * 0.99 ** i for i in range(20)]))
        self.assertEqual(down[max(down)]["boja"], "crveno")
        self.assertIsNone(up[min(up)]["boja"])                       # no 10-day average yet

    def test_point_in_time_no_look_ahead(self):
        base = [100 * (1 + 0.02 * ((i % 9) - 4)) for i in range(60)]
        a = T.colours(_closes(base))
        changed = base[:40] + [v * 3 for v in base[40:]]               # the future changes wildly
        b = T.colours(_closes(changed))
        days = sorted(a)
        for d in days[:40]:
            self.assertEqual(a[d], b[d])
        self.assertNotEqual([a[d]["boja"] for d in days[40:]], [b[d]["boja"] for d in days[40:]])

    def test_state_at_uses_the_day_before(self):
        days = {0: {"boja": "crveno", "vol_trend": "pada", "fng": 20}, D: {"boja": "zeleno", "vol_trend": "raste",
                                                                          "fng": 60},
                2 * D: {"boja": "crveno", "vol_trend": "pada", "fng": 70}}
        s = T.state_at(days, 2 * D + 3600)                            # an entry early on day 2
        self.assertEqual(s["boja"], "zeleno")                          # day 1's colour: day 2 is not closed yet
        self.assertEqual(s["boja_prije"], "crveno")
        self.assertEqual(s["vol_trend"], "raste")
        self.assertEqual(s["fng"], 70)                                 # published at 00:00 of day 2
        self.assertEqual(s["fng_klasa"], "pohlepa")
        self.assertEqual(T.zajedno(s), "zeleno/bez_straha")


class FearGreed(unittest.TestCase):
    def test_classes_match_the_api(self):
        for v, lab in ((0, "Extreme Fear"), (25, "Extreme Fear"), (26, "Fear"), (46, "Fear"), (47, "Neutral"),
                       (54, "Neutral"), (55, "Greed"), (75, "Greed"), (76, "Extreme Greed"), (100, "Extreme Greed")):
            self.assertEqual(T.fng_class(v), T.FNG_API[lab], v)
        self.assertIsNone(T.fng_class(None))

    def test_vol_trend(self):
        vol = {i * D: (100 if i < 7 else 120) for i in range(14)}
        self.assertEqual(T.vol_trends(vol)[13 * D][1], "raste")
        vol = {i * D: (100 if i < 7 else 95) for i in range(14)}
        self.assertEqual(T.vol_trends(vol)[13 * D][1], "ravno")
        self.assertNotIn(12 * D, T.vol_trends(vol))                    # needs 14 days


class Tables(unittest.TestCase):
    def test_stats_cluster_by_token_day(self):
        rows = [{"token": "a", "ts": 5, "ret": 0.1}, {"token": "a", "ts": 50, "ret": 0.3},
                {"token": "b", "ts": 5, "ret": -0.1}, {"token": "a", "ts": D + 5, "ret": 0.0}]
        s = T.stats(rows)
        self.assertEqual((s["n"], s["k"]), (4, 3))
        self.assertAlmostEqual(s["mean"], 0.075)
        self.assertFalse(s["dovoljno"])
        self.assertEqual(T.stats([])["n"], 0)

    def test_tagging_and_rates(self):
        days = {0: {"boja": "zeleno", "fng_klasa": "pohlepa", "vol_trend": "raste"},
                D: {"boja": "crveno", "fng_klasa": "strah", "vol_trend": "pada"}}
        ev = T.tag([{"token": "a", "t0": D + 100, "kind": "skok", "size": 0.8, "tier": "2-15M"},
                    {"token": "b", "t0": 50, "kind": "pad", "size": 0.4, "tier": "15-200M"}], days)
        self.assertEqual((ev[0]["boja"], ev[0]["boja_prije"]), ("crveno", "zeleno"))
        self.assertEqual(ev[1]["day"], 0)
        tokens = {"a": {"mcap": 5e6, "closes": [(0, 1.0), (D, 1.0)]}, "b": {"mcap": 20e6, "closes": [(0, 1.0), (D, 1.0)]}}
        td = T.token_days(tokens, days, now=2 * D)
        self.assertEqual(td[("boja", "zeleno", "svi")], 2)
        self.assertEqual(td[("boja", "crveno", "2-15M")], 1)
        tab = {(r["stanje"], r["tier"]): r for r in T.event_tables(ev, td)["boja"]}
        self.assertEqual(tab[("crveno", "svi")]["skokova"], 1)
        self.assertEqual(tab[("crveno", "svi")]["skok_na_100"], 50.0)
        self.assertEqual(tab[("zeleno", "15-200M")]["padova"], 1)
        self.assertEqual(tab[("zeleno", "15-200M")]["pad_med"], 0.4)

    def test_drops_mirror_rule(self):
        cl = [(i * D, 1.0) for i in range(10)] + [(10 * D, 0.6)] + [(i * D, 0.6) for i in range(11, 15)]
        ev = T.derive({"m": {"symbol": "M", "mcap": 10e6, "closes": cl}}, now=15 * D, drops=True)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["kind"], "pad")
        self.assertAlmostEqual(ev[0]["size"], 0.4, places=3)
        self.assertEqual(ev[0]["tier"], "15-200M")                     # 10M now x 1.0 / 0.6 at the start
        small = T.derive({"m": {"symbol": "M", "mcap": 10_000, "closes": cl}}, now=15 * D, drops=True)
        self.assertEqual(small, [])                                    # under 30k: not analysed

    def test_out_of_sample_split(self):
        rows = []
        for i in range(30):
            good = i % 2 == 0
            for k in range(3):
                rows.append({"token": f"t{k}", "ts": i * D + 10, "ret": 0.05 if good else -0.05,
                             "s": {"boja": "zeleno" if good else "crveno", "boja_prije": "zuto", "fng": 60}})
        tr, te, cut = T.split(rows)
        self.assertEqual(cut, 20 * D)
        self.assertTrue(all(r["ts"] < cut for r in tr) and all(r["ts"] >= cut for r in te))
        o = T.oos(rows)
        self.assertEqual(o["odabran"], "samo_zeleno")                  # chosen on the train days
        self.assertEqual(o["filtri"]["samo_zeleno"]["maknuto"], 15)    # the 5 red test days x 3 tokens
        self.assertAlmostEqual(o["odabran_test"]["mean"], 0.05)
        self.assertGreater(o["razlika"], 0)
        # a filter that only looks good on the test days is never picked
        rows2 = [dict(r, ret=(-0.05 if r["s"]["boja"] == "zeleno" else 0.05) if r["ts"] < cut else r["ret"]) for r in rows]
        self.assertNotEqual(T.oos(rows2)["odabran"], "samo_zeleno")


class Run(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p, self.btc = F.build(self.dir)
        self.logs = []

    def run_once(self, **kw):
        return T.run(F.NOW, self.p, F.fetch_for(self.btc), log=self.logs.append, council=False, **kw)

    def test_full_pass_and_backfill_once(self):
        calls = []
        f = F.fetch_for(self.btc)
        f["btc"] = lambda days, g=f["btc"]: calls.append(days) or g(days)
        res = T.run(F.NOW, self.p, f, log=self.logs.append, council=False)
        self.assertEqual(calls, [T.KEEP_D])                            # the backfill: 400 days of closes
        self.assertGreaterEqual(res["dani"], 200)
        self.assertEqual(res["tokena_sa_svijecama"], 30)
        self.assertEqual(res["preskoceno"]["ispod_30k"], 1)
        self.assertEqual(res["preskoceno"]["bez_svijeca"], 1)
        self.assertEqual(res["skokova"], 90)                           # every stored tiered jump
        self.assertGreaterEqual(res["padova"], 1)
        self.assertTrue(res["slijede"]["dovoljno"])
        self.assertGreater(res["slijede"]["protiv"], 0)                # the tokens that move on their own
        self.assertEqual(res["pravilo"]["demo"]["svi"]["n"], 24)       # the nauceno rows are not the day rule
        self.assertEqual(res["pravilo"]["novcanici"]["svi"]["n"], 29)  # the 20k entry is not analysed
        self.assertEqual(res["pravilo"]["sjena"]["svi"]["n"], 150)     # profile "pravilo" only
        self.assertEqual(res["pravilo"]["replay"]["oos"]["odabran"], "samo_zeleno")
        line = [x for x in self.logs if x.startswith(T.PREFIX)]
        self.assertEqual(len(line), 1)
        self.assertIn("mrežnih poziva 1", line[0])
        con = sqlite3.connect(self.p["market"])
        self.assertGreater(con.execute("SELECT COUNT(*) FROM trziste_4h").fetchone()[0], 100)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM trziste_tok").fetchone()[0], 30)
        self.assertIsNotNone(T.kv_get(con, "backfill"))
        con.close()
        calls.clear()
        T.run(F.NOW + 6 * 3600, self.p, f, log=self.logs.append, council=False)
        self.assertEqual(calls, [15])                                  # a normal run: the last 15 closes only

    def test_empty_databases_never_raise(self):
        d = tempfile.mkdtemp()
        p = {k: os.path.join(d, f"{k}.db") for k in ("market", "midcap", "veliki", "insajderi", "league")}
        res = T.run(F.NOW, p, {"btc": lambda days: [], "fng": lambda n: [], "slug": lambda s: []},
                    log=self.logs.append, council=False)
        self.assertEqual(res["tokena_sa_svijecama"], 0)
        self.assertFalse(T.ready(res))
        a = T.answers(res)
        self.assertEqual(a["slijede"].split(" (")[0], "Nedovoljno podataka")
        self.assertEqual(a["pravilo"], "Nedovoljno podataka.")

    def test_page_empty_and_synthetic(self):
        from ui import trziste as U
        with mock.patch.object(store, "DB", os.path.join(self.dir, "nema.db")):
            t, body = U.page({}, now=F.NOW)
        self.assertEqual(t, "Tržište i tokeni")
        self.assertIn("Još nema izračuna", body)
        self.run_once()
        with mock.patch.object(store, "DB", self.p["market"]), mock.patch.object(T, "paths", lambda: self.p):
            for d in ("30", "90", "180", "nešto"):
                t, body = U.page({"d": d}, now=F.NOW)
                for s in ("Prate li tokeni tržište?", "Kad se događaju skokovi, a kad padovi?",
                          "Bi li mirovanje u strahu i kupnja kad BTC krene gore popravili rezultat?", "tz-fig",
                          "Izvor: alternative.me", "statistika, ne tvrdnja", "<details>"):
                    self.assertIn(s, body, (d, s))
                self.assertNotIn("manipulacija dokazana", body)
                self.assertNotIn("—", body)                                  # no em dashes
            self.assertIn("korak: 4 sata", U.page({"d": "30"}, now=F.NOW)[1])
            self.assertIn("korak: 1 dan", U.page({"d": "180"}, now=F.NOW)[1])
            tok = U.token_html("Tok03" + "x" * 38, now=F.NOW)
            self.assertIn("Tržište i ovaj token", tok)
            self.assertIn("cijena tokena", tok)
            self.assertEqual(U.token_html("nepoznat", now=F.NOW), "")

    def test_route_menu_and_help(self):
        import run_ui
        from ui import glossary, html
        with mock.patch.object(store, "DB", os.path.join(self.dir, "nema.db")):
            t, body = run_ui.route("/trziste", {})
        self.assertIn("Tržište i tokeni", body)
        self.assertIn("/trziste", {p["href"] for _s, items in html.SECTIONS for p in items})
        self.assertIn("/trziste", html.INTRO)
        self.assertIsNotNone(glossary.page_key("/trziste"))
        from ui import tokens
        self.assertIn('href="/trziste"', tokens.TRZISTE_LINK)

    def test_mcp_tool(self):
        from ui import mcpapi
        tools = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(tools["get_market_regime"]["annotations"]["readOnlyHint"])
        with mock.patch.object(store, "DB", os.path.join(self.dir, "nema.db")):
            d, err = mcpapi._tool("get_market_regime", {})
        self.assertTrue(err)
        self.run_once()
        with mock.patch.object(store, "DB", self.p["market"]):
            d, err = mcpapi._tool("get_market_regime", {"token": "Tok00" + "x" * 38})
        self.assertFalse(err)
        self.assertIn("zelen", d["pravilo_boje"])
        self.assertEqual(d["token"]["token"], "Tok00" + "x" * 38)
        self.assertIn("boja", d["dogadaji"])
        self.assertIn("replay", d["ulazi"])
        self.assertIn("ne tvrdnja", d["napomena"])
        with mock.patch.object(store, "DB", self.p["market"]):
            c = T.critic_summary()
        self.assertIn("filtri_oos", c)
        json.dumps(d, ensure_ascii=False)

    def test_council_once(self):
        from trade import settings
        from vijece import store as vstore
        con = vstore.connect(os.path.join(self.dir, "trade.db"))
        sub = []

        def fake_submit(con_, kid, title, interp, improve, ev, pc):
            sub.append((kid, title, interp, improve, ev, pc))
            return {"id": len(sub)}
        with mock.patch("ui.assistnotes.submit_suggestion", fake_submit):
            empty = {"ts": F.NOW, "skokova": 0, "pravilo": {}}
            self.assertIsNone(T.council_once(empty, F.NOW, con, log=self.logs.append))   # nothing to say yet
            self.assertEqual(sub, [])
            self.assertIsNone(settings.raw(con).get(T.ONCE_KEY))
            res = self.run_once()
            self.assertTrue(T.ready(res))
            self.assertEqual(T.council_once(res, F.NOW, con, log=self.logs.append), 1)
            self.assertIsNone(T.council_once(res, F.NOW + D, con, log=self.logs.append))  # once
        self.assertEqual(len(sub), 1)
        kid, title, interp, improve, ev, pc = sub[0]
        self.assertEqual(kid, vstore.CLAUDE_KID)
        self.assertIn("Režim tržišta", title)
        self.assertIsNone(pc)                                         # no setting is changed: a shadow first
        self.assertIn("SAMO sjena", improve)
        self.assertEqual(ev["predlozena_promjena"]["vrsta"], "samo_sjena")
        self.assertIn("replay", ev["skupovi"])
        self.assertTrue(settings.raw(con).get(T.ONCE_KEY))
        con.close()

    def test_council_real_submit_stores_one_note(self):
        from vijece import store as vstore
        con = vstore.connect(os.path.join(self.dir, "trade2.db"))
        res = self.run_once()
        nid = T.council_once(res, F.NOW, con, log=self.logs.append)
        self.assertIsNotNone(nid)
        n = con.execute("SELECT COUNT(*) FROM assistant_notes WHERE kind='suggestion'").fetchone()[0]
        self.assertEqual(n, 1)
        con.close()


class ReplayTrades(unittest.TestCase):
    def test_run_keeps_the_base_trades_apart(self):
        from veliki import midcap, replay
        d = tempfile.mkdtemp()
        path = os.path.join(d, "midcap.db")
        con = midcap.connect(path)
        con.close()
        res = {"tokens": 3, "_trades": [["m", 100, 0.01]]}
        with mock.patch.object(replay, "compute", lambda *a, **k: dict(res)), \
                mock.patch.object(replay, "line", lambda r: "x"):
            out = replay.run(now=F.NOW, log=lambda s: None, path=path, btc=[])
        self.assertNotIn("_trades", out)
        con = midcap.ro(path)
        self.assertEqual(midcap.kv_get(con, replay.KV_TRADES)["trades"], [["m", 100, 0.01]])
        self.assertNotIn("_trades", midcap.kv_get(con, replay.KV))
        con.close()


if __name__ == "__main__":
    unittest.main()
