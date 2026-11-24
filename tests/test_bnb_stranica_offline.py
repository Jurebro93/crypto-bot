"""/bnb (ui/bnb_stranica.py, 24.11.): the BNB page shows the summary, the pumps, the wallets that buy before them and
the measurement from a bnb.db built here; honest empty states without the database; the route and the menu."""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bnb import store  # noqa: E402
from ui import bnb_stranica  # noqa: E402

NOW = 1_764_000_000
HOSTILE = re.compile(r"<script>alert|<img src=x|\"><img")


class Page(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "bnb.db")
        self.env = mock.patch.dict(os.environ, {"BNB_DB": self.path, "BNB_ON": "1"})
        self.env.start()
        con = store.connect(self.path)
        con.execute("INSERT INTO bnb_tokens (chain, token, symbol, name, meme) VALUES ('bsc', '0xaaa1', 'CAKEDOG', 'Cake Dog', 1)")
        con.execute("INSERT INTO bnb_tokens (chain, token, symbol, name, meme) VALUES ('bsc', '0xbbb2', 'XSS', '<script>alert(1)</script>', 1)")
        con.execute("INSERT INTO bnb_events (chain, eid, kind, token, symbol, t0, peak_ts, peak_x, tier, peak_mc, mcap0, n_part, src, fetched)"
                    " VALUES ('bsc', 'e1', 'pumpa', '0xaaa1', 'CAKEDOG', ?, ?, 3.4, 'pumpa15', 21e6, 4e6, 57, 'gt', 1)", (NOW - 7200, NOW - 3600))
        con.execute("INSERT INTO bnb_events (chain, eid, kind, token, symbol, t0, peak_ts, peak_x, tier, peak_mc, mcap0, n_part, src, fetched)"
                    " VALUES ('bsc', 'e2', 'pumpa', '0xbbb2', '<script>alert(1)</script>', ?, ?, 2.1, 'pumpa2', 3e6, 1.2e6, 12, 'dex', 0)", (NOW - 90000, NOW - 86000))
        pumps = [{"symbol": "CAKEDOG", "token": "0xaaa1", "t0": NOW - 7200, "tier": "pumpa15", "lead_min": 37.0, "usd_in": 1200.0, "usd_out": 3100.0},
                 {"symbol": "XSS", "token": "0xbbb2", "t0": NOW - 90000, "tier": "pumpa2", "lead_min": 12.0, "usd_in": 300.0, "usd_out": 500.0}]
        con.execute("INSERT INTO bnb_pp (chain, owner, members, n_members, cls, why, n_pumps15, n_pumps2, n_tokens, med_lead_min, pnl_sol, pnl_usd, pumps, confirmed_ts, last_seen, updated)"
                    " VALUES ('bsc', '0xWALLETaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1111', '[]', 1, 'prije_pumpe', 'kupio prije skoka na 3 tokena i prodao u rast', 2, 1, 3, 37.0, 0, 2600.0, ?, ?, ?, ?)",
                    (json.dumps(pumps), NOW - 400, NOW - 3000, NOW))
        con.execute("INSERT INTO bnb_pp (chain, owner, members, n_members, cls, why, n_pumps15, n_pumps2, n_tokens, med_lead_min, pnl_sol, pnl_usd, pumps, confirmed_ts, last_seen, updated)"
                    " VALUES ('bsc', '0xWALLETbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb2222', '[]', 1, 'kandidat', 'dva tokena', 0, 2, 2, 9.0, 0, -40.0, '[]', NULL, ?, ?)",
                    (NOW - 100, NOW))
        con.execute("INSERT INTO bnb_pp (chain, owner, members, n_members, cls, why, n_tokens, pumps, updated)"
                    " VALUES ('bsc', '0xWALLETcccc', '[]', 1, 'bot', 'bot', 9, '[]', ?)", (NOW,))
        con.execute("INSERT INTO bnb_mjera (chain, source, gid, wallet, token, symbol, seen_ts, delay_s, entry_ts, entry_price, entry_mcap, status, exit_reason, ret_gross, ret_net_50, ret_net_250)"
                    " VALUES ('bsc', 'bnb_prije_pumpe', 'g1', '0xWALLETaaaa', '0xaaa1', 'CAKEDOG', ?, 48, ?, 0.01, 5.5e6, 'closed', 'tp', 0.12, 0.11, 0.07)",
                    (NOW - 5000, NOW - 4950))
        con.execute("INSERT INTO bnb_runs (ts, kind, secs, calls, detail) VALUES (?, 'pass', 1500.0, ?, '')",
                    (NOW - 600, json.dumps({"rpc": "rpc-bsc.48.club", "free": {"gt": 120, "dex": 30}})))
        con.execute("INSERT INTO bnb_kv VALUES ('last', ?)", (json.dumps({"lijevak": {
            "pumpe15_1h": 3, "pumpe15_1d": 5, "pumpe2_1h": 2, "pumpe2_1d": 4, "duboko": 1, "procitano": 24, "izvan_dosega": 9,
            "prazno": 0, "rani": 300, "rani_prodali": 60, "blizu_praga": 2, "grupe": 1, "potvrdjeno": 1,
            "pokrivenost_pre_med": 1.0, "pokrivenost_skok_med": 1.0, "n_pokrivenost": 24, "klase": {"prije_pumpe": 1}}}),))
        con.commit()
        con.close()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_four_sections_with_the_data(self):
        title, html = bnb_stranica.page({}, NOW)
        self.assertEqual(title, "BNB Chain: pumpe i novčanici")
        for sid in ("sazetak", "pumpe", "novcanici", "mjerenje", "metoda"):
            self.assertIn(f"<h2 id={sid}>", html, sid)
        # summary: counts from bnb.db and the funnel line
        self.assertIn("pumpi pronađeno", html)
        self.assertIn("5 / 4", html)                                        # 15 M $+ / 2–15 M $ in a day
        self.assertIn("Rani kupci na pročitanim pumpama: 300, od njih prodali u pumpu 60", html)
        self.assertIn("rpc-bsc.48.club", html)
        self.assertIn("prije 10 min", html)                                 # the last pass
        # pumps: the newest first, DexScreener link, tier, peak
        pumps = html.split("<h2 id=pumpe>")[1].split("<h2 id=novcanici>")[0]
        self.assertLess(pumps.index("CAKEDOG"), pumps.index("XSS") if "XSS" in pumps else len(pumps) + 1)
        self.assertIn('href="https://dexscreener.com/bsc/0xaaa1"', pumps)
        self.assertIn("15 M $ i više", pumps)
        self.assertIn("3,4×", pumps)
        self.assertIn("pročitano", pumps)
        # wallets: the confirmed one first, the candidate after, the excluded class never; a fold with every jump
        wal = html.split("<h2 id=novcanici>")[1].split("<h2 id=mjerenje>")[0]
        self.assertEqual(wal.count("<details class=bnb-w>"), 2)
        self.assertLess(wal.index("0xWALL…1111"), wal.index("0xWALL…2222"))
        self.assertNotIn("0xWALLETcccc", wal)
        self.assertIn("potvrđeno", wal)
        self.assertIn("kandidat", wal)
        self.assertIn('href="https://bscscan.com/address/0xWALLETaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1111"', wal)
        self.assertIn("37 min prije skoka", wal)
        self.assertIn("3 tokena", wal)
        self.assertIn("zadnji put prije 50 min", wal)
        self.assertIn('class=adm-only>· uloženo 1,2k\xa0$, izašlo 3,1k\xa0$', wal)   # amounts only for the owner
        self.assertIn("Ostvareno na tim skokovima", wal)
        self.assertIn("adm-only", wal)
        # measurement: by source and the rows
        mj = html.split("<h2 id=mjerenje>")[1].split("<h2 id=metoda>")[0]
        self.assertIn("novčanici prije pumpe", mj)
        self.assertIn("48 s", mj)
        self.assertIn("zatvoreno (cilj)", mj)
        self.assertIn("+11,0\xa0%", mj)
        # the hostile symbol is escaped everywhere
        self.assertIsNone(HOSTILE.search(html))
        self.assertIn("&lt;script&gt;", html)

    def test_honest_empty_states(self):
        con = store.connect(self.path)
        for t in ("bnb_events", "bnb_pp", "bnb_mjera", "bnb_kv", "bnb_runs"):
            con.execute(f"DELETE FROM {t}")
        con.commit()
        con.close()
        _t, html = bnb_stranica.page({}, NOW)
        self.assertIn("Još nijedna pumpa nije pronađena.", html)
        self.assertIn("Još nijedan novčanik ne prolazi pravilo", html)
        self.assertIn("Mjerenje još nije počelo", html)
        self.assertIn("Nijedan novčanik još nije potvrđen na novijim podacima", html)
        self.assertNotIn("Traceback", html)

    def test_without_the_database(self):
        with mock.patch.dict(os.environ, {"BNB_DB": os.path.join(self.tmp.name, "nema.db")}):
            title, html = bnb_stranica.page({}, NOW)
        self.assertEqual(title, "BNB Chain: pumpe i novčanici")
        self.assertIn("BNB baza još ne postoji", html)
        self.assertNotIn("<h2 id=pumpe>", html)


class Wiring(unittest.TestCase):
    def test_route_and_menu(self):
        import run_ui
        from ui import html as H
        with mock.patch.dict(os.environ, {"BNB_DB": os.path.join(tempfile.mkdtemp(), "nema.db")}):
            title, body = run_ui.route("/bnb", {})
        self.assertEqual(title, "BNB Chain: pumpe i novčanici")
        hrefs = {p["href"]: p for _s, ps in H.SECTIONS for p in ps}
        self.assertIn("/bnb", hrefs)
        self.assertEqual(hrefs["/bnb"]["name"], "BNB Chain")


if __name__ == "__main__":
    unittest.main()
