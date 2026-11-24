"""19.11. navečer: Birdeye, a bounded second source for the pump-wallet discovery (insajderi/birdeye.py), offline with
a fake HTTP: the month's CU never exceeded, paging and the frame choice, the refresh rule, the three uses (cross-check,
new candidates, tags next to our classes), the missing key, the permission refusal, the rate-limit back-off, the
history queue's source "birdeye", the pass stage, and the admin section (data / no key / no table).

    python3 -m unittest tests.test_birdeye_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import birdeye as be, store  # noqa: E402

D = 86400
NOW = 1_795_400_000
C = store.config({})


def addr(name):
    return (name + "1" * 44)[:44]


def ev(k, tier, days_ago):
    t0 = NOW - days_ago * D
    tok = addr(f"Tok{k}")
    return {"eid": f"j:{tok}:{t0}", "token": tok, "t0": t0, "tier": tier, "win_end": t0 + 3600}


class Fake:
    """GET /defi/v2/tokens/top_traders: items per mint (a list of dicts), paged by offset / limit; script: a list of
    answers to give first ("many" = Too many requests, "perm" = lacks permissions)."""

    def __init__(self, items=None, n=25, script=()):
        self.items, self.n, self.script, self.calls = items or {}, n, list(script), []

    def __call__(self, url, headers):
        qs = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        self.calls.append((qs, dict(headers)))
        if self.script:
            s = self.script.pop(0)
            if s == "many":
                return 200, {"success": False, "message": "Too many requests"}
            if s == "perm":
                return 200, {"success": False, "message": "Your API key lacks sufficient permissions to access this "
                                                          "resource."}
        mint = qs["address"]
        rows = self.items.get(mint)
        if rows is None:
            rows = [{"owner": addr(f"O{mint[:6]}{i}"), "tags": [], "realizedPnl": 100.0 - i, "totalPnl": 100.0 - i,
                     "trade": 4, "tradeBuy": 2, "tradeSell": 2, "volumeBuyUSD": 1000.0, "volumeSellUSD": 1100.0,
                     "avgBuyPrice": 1.0, "avgSellPrice": 1.1, "firstTradeUnixTime": NOW - 5 * D,
                     "lastTradeUnixTime": NOW - D} for i in range(self.n)]
        off, lim = int(qs["offset"]), int(qs["limit"])
        return 200, {"success": True, "data": {"items": rows[off:off + lim]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = store.connect(os.path.join(self.tmp.name, "i.db"))
        self.lines = []
        self.slept = []
        self.t = [0.0]
        env = mock.patch.dict(os.environ, {"BIRDEYE_API_KEY": "k-test"})
        env.start()
        self.addCleanup(env.stop)
        be._GATE["next"] = 0.0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def sleep(self, s):
        self.slept.append(s)
        self.t[0] += s

    def fetch(self, events, fake, now=NOW, c=None):
        return be.fetch(self.con, c or C, events, now, get=fake, sleep=self.sleep, clock=lambda: self.t[0],
                        log=self.lines.append)


class Fetch(Base):
    def test_paging_frames_order_and_the_key_header(self):
        evs = [ev(1, "pumpa2", 2), ev(2, "pumpa15", 20), ev(3, "pumpa15", 3), ev(4, "pumpa15", 120)]
        f = Fake()
        res = self.fetch(evs, f)
        self.assertEqual(res["old"], 1)                                     # 120 days: older than 90d, counted
        order = []
        for qs, h in f.calls:
            if qs["address"] not in order:
                order.append(qs["address"])
        self.assertEqual(order, [evs[2]["token"], evs[1]["token"], evs[0]["token"]])   # 15M first, newest first
        frames = {qs["address"]: qs["time_frame"] for qs, _h in f.calls}
        self.assertEqual(frames, {evs[2]["token"]: "7d", evs[1]["token"]: "30d", evs[0]["token"]: "7d"})
        offs = [int(qs["offset"]) for qs, _h in f.calls if qs["address"] == evs[2]["token"]]
        self.assertEqual(offs, [0, 10, 20])                                 # 3 pages of 10
        self.assertTrue(all(qs["limit"] == "10" and qs["sort_by"] == "realized_pnl" for qs, _h in f.calls))
        self.assertEqual(f.calls[0][1]["X-API-KEY"], "k-test")
        self.assertEqual(f.calls[0][1]["x-chain"], "solana")
        self.assertEqual(res["rows"], 75)
        self.assertEqual(be.usage(self.con, NOW), (9, 270))
        self.assertTrue(all(abs(s - 1 / 0.7) < 1e-6 for s in self.slept))   # the pace: 0.7 calls a second
        self.assertEqual(be.line(res, self.con, C, NOW), "birdeye: 3 tokena, 75 trgovaca, CU ovaj mjesec 270/25,000")
        f2 = Fake(n=12)                                                     # a short list: the third page is not asked
        self.fetch([ev(9, "pumpa15", 1)], f2)
        self.assertEqual([int(qs["offset"]) for qs, _h in f2.calls], [0, 10])

    def test_month_budget_never_exceeded(self):
        evs = [ev(k, "pumpa15", 1 + k) for k in range(10)]
        f = Fake()
        self.fetch(evs, f, c=dict(C, birdeye=dict(C["birdeye"], cu_month=200)))
        self.assertEqual(len(f.calls), 6)
        self.assertLessEqual(be.usage(self.con, NOW)[1], 200)
        self.assertEqual(self.fetch(evs, Fake(), c=dict(C, birdeye=dict(C["birdeye"], cu_month=200)))["calls"], 0)

    def test_refresh_rule(self):
        evs = [ev(1, "pumpa15", 1)]
        self.fetch(evs, Fake())
        f = Fake()
        self.fetch(evs, f, now=NOW + 13 * D)
        self.assertEqual(f.calls, [])                                       # read within 14 days
        f = Fake()
        self.fetch(evs, f, now=NOW + 15 * D)
        self.assertEqual(len(f.calls), 3)

    def test_missing_key_permission_refusal_and_rate_limit(self):
        with mock.patch.dict(os.environ, {"BIRDEYE_API_KEY": ""}):
            f = Fake()
            self.assertTrue(self.fetch([ev(1, "pumpa15", 1)], f)["no_key"])
            self.fetch([ev(1, "pumpa15", 1)], f)
        self.assertEqual(f.calls, [])
        self.assertEqual(self.lines.count("birdeye: ključ nije postavljen"), 1)   # once a day
        f = Fake(script=["perm"])
        self.fetch([ev(1, "pumpa15", 1), ev(2, "pumpa15", 2)], f)
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(len([x for x in self.lines if "nije dostupan s ovim ključem" in x]), 1)
        f2 = Fake()
        self.fetch([ev(1, "pumpa15", 1)], f2)
        self.assertEqual(f2.calls, [])                                      # off for the rest of the day
        f3 = Fake(script=["many"])
        self.fetch([ev(1, "pumpa15", 1)], f3, now=NOW + D)
        self.assertEqual(len(f3.calls), 4)                                  # the refused one retried once, 3 pages
        self.assertTrue(any(s > 2.0 for s in self.slept))                   # a longer wait before the retry
        self.assertEqual(self.con.execute("SELECT rows FROM be_tok").fetchone()[0], 25)


class Uses(Base):
    def test_candidates_cross_check_tags_and_the_queue(self):
        toks = [ev(k, "pumpa15" if k < 2 else "pumpa2", 1 + k) for k in range(4)]
        star, sn, sm, mem, botw = addr("Star"), addr("Snipe"), addr("Smart"), addr("Member"), addr("Botty")

        def row(o, real, tags=()):
            return {"owner": o, "tags": list(tags), "realizedPnl": real, "totalPnl": real, "trade": 2, "tradeBuy": 1,
                    "tradeSell": 1, "volumeBuyUSD": 10.0, "volumeSellUSD": 20.0, "avgBuyPrice": 1.0,
                    "avgSellPrice": 2.0, "firstTradeUnixTime": NOW - 9 * D, "lastTradeUnixTime": NOW - D}
        items = {}
        for i, e in enumerate(toks):
            rows = [row(star, 500.0), row(sn, 400.0, ["sniper"]), row(sm, -5.0, ["smart_trader"] if i < 2 else [])]
            if i == 0:
                rows += [row(mem, 50.0), row(botw, 30.0, ["bundler"])]
            items[e["token"]] = rows
        self.fetch(toks, Fake(items))
        for eid, w, o in ((toks[0]["eid"], mem, "G1"), (toks[1]["eid"], mem, "G1"), (toks[0]["eid"], botw, "B1")):
            self.con.execute("INSERT INTO i2_events (eid, kind, token, t0, tier, win_end) VALUES (?,?,?,?,?,?)",
                             (eid, "jump", eid.split(":")[1], 1, "pumpa15", 2)) if not self.con.execute(
                "SELECT 1 FROM i2_events WHERE eid=?", (eid,)).fetchone() else None
            self.con.execute("INSERT INTO i2_part (eid, wallet, owner, bought_before, sold_into) VALUES (?,?,?,1,1)",
                             (eid, w, o))
        self.con.execute("INSERT INTO i2_pp (owner, members, cls) VALUES ('G1', ?, 'prije_pumpe')", (json.dumps([mem]),))
        self.con.execute("INSERT INTO i2_pp (owner, members, cls) VALUES ('B1', ?, 'bot')", (json.dumps([botw]),))
        self.con.commit()
        out = be.analyze(self.con, C, toks, NOW)
        cand = {r[0]: r for r in self.con.execute("SELECT owner, n_tokens, n15, sum_realized_usd, tags, last_ts, smart_n "
                                                  "FROM be_cand")}
        self.assertEqual(cand[star][1:4], (4, 2, 2000.0))                  # 4 pumps, 2 of them >= 15M
        self.assertNotIn(sn, [o for o, r in cand.items() if r[1] >= 3])    # tagged sniper on those rows: not a candidate
        self.assertEqual(cand[sm][6], 2)                                    # smart_trader on 2 pumps
        self.assertEqual((out["candidates"], out["smart"], out["tokens_read"]), (1, 1, 4))
        self.assertEqual((out["groups_checked"], out["groups_seen_in_top"], out["share"]), (1, 1, 1.0))
        g = self.con.execute("SELECT n_checked, n_seen, agree FROM be_pp WHERE owner='G1'").fetchone()
        self.assertEqual(tuple(g), (2, 1, None))
        self.assertEqual(self.con.execute("SELECT agree, tags FROM be_pp WHERE owner='B1'").fetchone(), (1, '["bundler"]'))
        self.assertEqual((out["tag_agree"], out["tag_disagree"]), (1, 0))
        md = "\n".join(be.md_section(self.con))
        self.assertIn("### Birdeye: u vrhu po ostvarenoj zaradi na N pumpi", md)
        self.assertIn(f"{star[:4]}…{star[-4:]} | 4 | 2 | 2,000", md)
        # the history queue: source "birdeye", right after the pump groups
        from wallets import povijest, store as wstore
        wc = wstore.connect(os.path.join(self.tmp.name, "w.db"))
        povijest.ensure(wc)
        src = povijest.sources(wc, {"insajderi_db": os.path.join(self.tmp.name, "i.db"), "holderi_db": None},
                               povijest.config())
        wc.close()
        kinds = [s for _w, s in src]
        self.assertIn((star, "birdeye"), src)
        self.assertLess(kinds.index("prije_pumpe_kandidat"), kinds.index("birdeye"))   # G1 is not confirmed yet

    def test_the_pass_stage_and_its_line(self):
        from insajderi import report, run
        from tests.test_insajderi2_offline import build_world, cfg, t0_of
        p, ch = build_world(self.tmp.name)
        lines = []
        with mock.patch.object(be, "http_get", Fake()), mock.patch.object(report, "OUT_DIR", self.tmp.name), \
                mock.patch.dict(os.environ, {"INSAJDERI_DB": p["insajderi_db"]}):
            s = run.run("once", now=t0_of(6) + 2 * D, cfg=cfg(), credits=100_000, fetch=ch.fetch, log=lines.append, **p)
        self.assertIn("birdeye", s["prije_pumpe"])
        self.assertIn("birdeye: 0 tokena, 0 trgovaca, CU ovaj mjesec 0/25,000", lines)
        self.assertTrue(any("birdeye" in x and "trajanje" in x for x in lines), lines)


class Admin(unittest.TestCase):
    def test_section_with_data_no_key_and_no_table(self):
        from ui import novadmin
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "i.db")
            con = store.connect(path)
            be.ensure(con)
            con.execute("INSERT INTO be_usage VALUES (?, 12, 360)", (be.month(NOW),))
            con.execute("INSERT INTO be_tok VALUES ('m1', '7d', 30, 'ok', ?)", (NOW,))
            con.execute("INSERT INTO be_cand VALUES (?,?,?,?,?,?,?,?)", (addr("Star<b>"), 4, 2, 2000.0, '["fresh"]',
                                                                         NOW - D, 0, NOW))
            con.commit()
            ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            pp = {"birdeye": {"groups_checked": 5, "groups_seen_in_top": 2, "tag_agree": 1, "tag_disagree": 0}}
            with mock.patch.dict(os.environ, {"BIRDEYE_API_KEY": "x"}):
                html = novadmin.birdeye_html(ro, pp, NOW)
            self.assertIn("360 od 25 000 jedinica", html.replace("\xa0", " "))
            self.assertIn("Novi novčanici iz Birdeyea: među najboljima po zaradi na 3 ili više skokova", html)
            self.assertIn("Kopiraj", html)
            self.assertIn("solscan.io/account/", html)
            self.assertNotIn("<b>Star", html)                                 # escaped
            with mock.patch.dict(os.environ, {"BIRDEYE_API_KEY": "", "BIRDEYE_PROXY_KEY": ""}):
                empty = novadmin.birdeye_html(sqlite3.connect(":memory:"), {}, NOW)
            self.assertIn("Ključ za Birdeye nije postavljen", empty)
            with mock.patch.dict(os.environ, {"BIRDEYE_API_KEY": "x"}):
                nothing = novadmin.birdeye_html(sqlite3.connect(":memory:"), {}, NOW)
            self.assertIn("Birdeye još ništa nije pročitao", nothing)
            ro.close()
            con.close()


class SharedBudget(unittest.TestCase):
    """20.11.: dugo's /defi/token_overview (18 CU) books into the same be_usage month row and stops at the cap of the
    month's total (insajderi + dugo); insajderi's own left_cu() sees dugo's spend."""

    def test_take_cap_and_dugo_stops(self):
        from usage import birdeye as budget
        from dugo import sources
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "insajderi.db")
            con = store.connect(p)
            be.ensure(con)
            con.execute("INSERT INTO be_usage VALUES (?, 10, 24970)", (be.month(NOW),))   # insajderi's 25,000 - 30
            con.commit()
            self.assertTrue(budget.take(18, NOW, p, limit=25000))
            self.assertFalse(budget.take(18, NOW, p, limit=25000))                        # 24,988 + 18 > 25,000
            self.assertEqual(budget.used(NOW, p), (11, 24988))
            self.assertEqual(be.usage(con, NOW), (11, 24988))                            # insajderi sees it
            con.close()
            self.assertEqual(budget.used(NOW + 40 * 86400, p), (0, 0))                   # a new month
            calls = []
            with mock.patch.dict(os.environ, {"BIRDEYE_API_KEY": "x", "INSAJDERI_DB": p}), \
                    mock.patch.object(sources.http, "_fetch", lambda req, t, retries=None: calls.append(1) or
                                      {"data": {"holder": 7}}), \
                    mock.patch.object(sources, "_BE_CAPPED", [False]), mock.patch("builtins.print"):
                self.assertEqual(sources.holders_birdeye("M", now=NOW + 40 * 86400), 7)   # next month: room
                self.assertEqual(budget.used(NOW + 40 * 86400, p), (1, 18))
                self.assertIsNone(sources.holders_birdeye("M", now=NOW))                  # this month: capped
                self.assertIsNone(sources.holders_birdeye("M", now=NOW + 40 * 86400))     # and stays off this process
            self.assertEqual(len(calls), 1)
        self.assertEqual(budget.CU_TOKEN_OVERVIEW, 18)
        self.assertEqual(budget.cap(), be.config(store.config())["cu_month"])


if __name__ == "__main__":
    unittest.main()
