"""16.11.2026. (vlasnik u chatu: "https://x.com/Adam_Tehc" = Adam kojeg je mislio; "možeš pratiti influencere od 30k+
followera i dodaj ih na listu"), offline, no network:

  - the threshold 30k, the ceiling 800; the first wave stays what it was ordered with (500 accounts, 100k+)
  - the second wave's order recorded once (kv, runs, a log line with his words), only after the first wave's
    discovery; its estimate (accounts x posts x price) logged before anything is spent
  - the candidates the first wave refused ONLY for "ispod 100k pratitelja" are reconsidered from what is stored:
    no followings, no user search, no profile lookup is paid again; only when they do not fill the ceiling the
    normal discovery goes on (followings of the accounts the first wave did not read)
  - the second wave's caps (twitterapi 25 $, OpenAI 8 $) stop it cleanly and are separate from the first wave's;
    the daily caps are 2,00 $ / 0,60 $; its accounts get the last 200 posts + up to 300 market posts over 12 months
  - Adam_Tehc is the owner's confirmed account (measured whatever its followers), the other candidates leave the
    waiting list, the candidate measured in the meantime stays only if it passes the normal filters on its own
  - the public hub and the app list with 800 accounts: 100 a page, every account on exactly one page, the sitemap
    has all of them

    python3 -m unittest tests.test_makro30k_offline
"""
import html
import json
import os
import re
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import twapi  # noqa: E402
from makroinf import classify, discover, fetch, racuni, report, run, score, store, web, xapi  # noqa: E402
from makroinf import public as mpub  # noqa: E402
from tests.test_makro2_offline import FakeX2, cfg, user  # noqa: E402
from tests.test_makroinf_offline import NOW, Base, fake_llm, outs  # noqa: E402
from trade import settings  # noqa: E402

D = 86400


def owner_file(tc, potvrdi=None):
    """The owner's file of the test (never the repo's): {} or his confirmation."""
    p = os.path.join(tc.tmp.name, "own.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"potvrdi": potvrdi or {}}, f)
    m = mock.patch.object(racuni, "OWNER_FILE", p)
    m.start()
    tc.addCleanup(m.stop)
    return p


def wave1_done(con, n=3, now=NOW):
    """n measured accounts, the first wave ordered and its discovery finished (the followings of a1 read)."""
    for k in range(n):
        con.execute("INSERT INTO accounts (handle, status, source, category, added_ts, regularity) VALUES (?, 'aktivan', "
                    "'sjeme', 'ta', 1, ?)", (f"a{k + 1}", 5 - k * 0.1))
    con.commit()
    assert discover.record_order(con, cfg(), now - D, lambda *_: None)
    store.kv(con, "otkrivanje", {"step": "gotovo", "krug": 1, "pratitelji": {"a1": [3, None]}, "dodano": []})
    con.commit()


def stored(con, h, fol, why=discover.WHY_WAVE1, status="odbijen", nf=2, bio="crypto macro analyst, BTC charts"):
    """A candidate the first wave's discovery stored (its profile and who of ours follows it), never probed."""
    con.execute("INSERT INTO disc (handle, name, followers, statuses, bio, status, why, ts, raw) VALUES (?,?,?,?,?,?,?,?,?)",
                (h, h, fol, 9000, bio, status, why, NOW - D, json.dumps(user(h, fol, bio))))
    for k in range(nf):
        con.execute("INSERT OR IGNORE INTO disc_edge VALUES (?,?,?)", (f"a{k + 1}", h.lower(), "follow"))
    con.commit()


class Config30k(Base):
    def test_threshold_ceiling_caps_and_depth(self):
        c = store.config({})
        self.assertEqual((c["min_followers"], c["expand_n"]), (30_000, 800))
        self.assertEqual((c["expand2_twapi_usd"], c["expand2_openai_usd"], c["day_twapi_usd"], c["day_openai_usd"]),
                         (25.0, 8.0, 2.0, 0.6))
        self.assertEqual((c["expand_twapi_usd"], c["expand_openai_usd"]), (40.0, 15.0))      # the first wave's stay
        w2 = fetch.wave2_cfg(c)
        self.assertEqual((w2["last_pages"] * w2["page_posts"], w2["depth_posts"], w2["months"]), (200, 300, 12))
        self.assertTrue(c["expand2_by_order"])
        # the first wave never goes past what it was ordered with
        w1 = discover._w1(c)
        self.assertEqual((w1["expand_n"], w1["min_followers"]), (500, 100_000))
        self.assertEqual(discover._w1(cfg(expand_n=7))["expand_n"], 7)

    def test_the_two_waves_have_separate_caps(self):
        c = store.config({})
        for k in ("pilot_twapi_done", "pilot_openai_done"):
            store.kv(self.con, k, "1")
        self.assertEqual(store.left(self.con, "twapi", "prosirenje2", NOW, c), 25.0)
        self.assertEqual(store.left(self.con, "openai", "prosirenje2", NOW, c), 8.0)
        store.book(self.con, "twitterapi", 35.16, "prosirenje", "mj", NOW)      # the server's state of the first wave
        store.book(self.con, "openai", 11.0, "prosirenje", "klasifikacija", NOW)
        store.book(self.con, "twitterapi", 3.0, "prosirenje2", "proba", NOW)
        self.assertAlmostEqual(store.left(self.con, "twapi", "prosirenje", NOW, c), 4.84, 6)
        self.assertAlmostEqual(store.left(self.con, "twapi", "prosirenje2", NOW, c), 22.0, 6)
        self.assertAlmostEqual(store.left(self.con, "openai", "prosirenje", NOW, c), 4.0, 6)
        self.assertEqual(store.left(self.con, "openai", "prosirenje2", NOW, c), 8.0)
        self.assertEqual(store.left(self.con, "twapi", "dan", NOW, c), 2.0)      # neither touches the day's caps
        self.assertEqual(store.left(self.con, "openai", "dan", NOW, c), 0.6)
        store.kv(self.con, "prosirenje2", {"twapi_usd": 4.0, "openai_usd": 1.0})   # the recorded caps win
        self.assertAlmostEqual(store.left(self.con, "twapi", "prosirenje2", NOW, c), 1.0, 6)
        sp = discover.phase_spend(self.con)
        self.assertEqual((sp["dubina"], sp["2. val: proba"]), (35.16, 3.0))
        self.assertIn("2. val (30k+) twitterapi 3,00 $ / 4,00 $", report.hour_line(self.con, NOW, c))


class Order2(Base):
    """The second order: recorded once, after the first wave's discovery, the estimate before the money."""

    def setUp(self):
        super().setUp()
        owner_file(self)

    def test_not_before_the_first_waves_discovery_is_done(self):
        for h in ("a1", "a2"):
            self.con.execute("INSERT INTO accounts (handle, status, source, category) VALUES (?, 'aktivan', 'sjeme', 'ta')",
                             (h,))
        logs = []
        self.assertFalse(discover.record_order2(self.con, cfg(), NOW, logs.append))       # no first order at all
        discover.record_order(self.con, cfg(), NOW, lambda *_: None)
        self.assertFalse(discover.record_order2(self.con, cfg(), NOW, logs.append))       # its discovery still runs
        self.assertEqual(logs, [])
        self.assertIsNone(store.kv(self.con, "nalog_prosirenje2"))
        self.assertFalse(discover.ordered2(self.con, cfg()))
        # the first order keeps its own numbers although the ceiling and the threshold moved
        self.assertEqual(store.kv_json(self.con, "nalog_prosirenje")["cilj"], 500)

    def test_recorded_once_with_the_quote_caps_and_the_estimate_before_any_spend(self):
        wave1_done(self.con)
        stored(self.con, "mid1", 60_000)
        logs = []
        c = cfg()
        self.assertTrue(discover.record_order2(self.con, c, NOW, logs.append))
        rec = store.kv_json(self.con, "nalog_prosirenje2")
        self.assertEqual(rec["citat"], "možeš pratiti influencere od 30k+ followera i dodaj ih na listu")
        self.assertEqual((rec["id"], rec["ts"], rec["kada"]), ("prosirenje2-1611-30k", NOW, "16.11.2026."))
        self.assertEqual((rec["prag_pratitelja"], rec["prag_prije"], rec["cilj"], rec["cilj_prije"]),
                         (30_000, 100_000, 800, 500))
        self.assertEqual((rec["strop_twapi_usd"], rec["strop_openai_usd"], rec["dan_twapi_usd"], rec["dan_openai_usd"]),
                         (25.0, 8.0, 2.0, 0.6))
        self.assertEqual(rec["dubina"], {"zadnjih": 200, "trzisnih": 300, "mjeseci": 12})
        caps = store.kv_json(self.con, "prosirenje2")
        self.assertEqual((caps["twapi_usd"], caps["openai_usd"], caps["nalog"]), (25.0, 8.0, rec["id"]))
        self.assertEqual([k for (k,) in self.con.execute("SELECT kind FROM runs ORDER BY rowid")],
                         ["nalog_prosirenje", "nalog_prosirenje2"])
        self.assertEqual(len(logs), 2)
        self.assertIn("2. val proširenja po nalogu vlasnika (16.11.2026.: „možeš pratiti influencere od 30k+", logs[0])
        self.assertIn("prag 30k pratitelja (prije 100k), strop 800 računa (prije 500", logs[0])
        self.assertIn("twitterapi 25,00 $, OpenAI 8,00 $", logs[0])
        self.assertIn("zadnjih 200 + do 300 tržišnih objava u 12 mjeseci", logs[0])
        self.assertIn("procjena 2. vala (prije troška; računi × objave × cijena)", logs[1])
        self.assertIn("1 odbijenih samo zbog „ispod 100k pratitelja”", logs[1])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM spend").fetchone()[0], 0)   # nothing spent yet
        est = store.kv_json(self.con, "procjena2")
        self.assertEqual((est["racuna_sada"], est["cilj"], est["novih"]), (3, 800, 797))
        self.assertEqual(est["stropovi"], {"twapi": 25.0, "openai": 8.0, "dan_twapi": 2.0, "dan_openai": 0.6})
        # once: a later round neither logs nor rewrites it; the first wave's record and caps are untouched
        self.assertTrue(discover.record_order2(self.con, c, NOW + 600, logs.append))
        self.assertEqual(len(logs), 2)
        self.assertEqual(store.kv_json(self.con, "nalog_prosirenje2")["ts"], NOW)
        self.assertEqual(store.kv_json(self.con, "prosirenje")["twapi_usd"], 40.0)
        self.assertTrue(discover.ordered2(self.con, c))
        self.assertFalse(discover.record_order2(self.con, cfg(expand2_by_order=False), NOW, logs.append))
        sm = discover.summary(self.con)
        self.assertEqual(sm["val2"]["nalog"]["id"], rec["id"])
        self.assertEqual(sm["val2"]["stropovi"], {"twapi": 25.0, "openai": 8.0})
        card = report._order_html(self.db, html.escape)                           # the owner's card shows both orders
        self.assertIn("Proširenje po tvom nalogu (15.11.2026. navečer)", card)
        self.assertIn("2. val po tvom nalogu (16.11.2026.", card)
        self.assertIn("prag 30k pratitelja, strop 800 računa (sada 3)", card)
        self.assertIn("potrošeno 0,00 $ / 25,00 $", card)

    def test_the_estimate_of_500_to_800_fits_the_caps(self):
        for k in range(500):
            self.con.execute("INSERT INTO accounts (handle, status, source, category) VALUES (?, 'aktivan', 'prosirenje', "
                             "'ta')", (f"w{k}",))
        self.con.commit()
        c = store.config()
        e = discover.estimate2(self.con, c, NOW)
        self.assertEqual((e["racuna_sada"], e["novih"], e["cilj"], e["prag_pratitelja"]), (500, 300, 800, 30_000))
        r = e["racun"]
        # accounts x posts x price, each part reproducible from the line's own numbers
        self.assertEqual((r["proba_racuna"], r["objava_po_probi"], r["dubina_zadnjih"]), (600, 20, 180))
        self.assertAlmostEqual(e["twapi"]["proba"], 600 * 20 * 0.00015, 2)
        self.assertAlmostEqual(e["twapi"]["dubina_novi"], 300 * (180 + r["dubina_mjesecnih"]) * 0.00015, 1)
        self.assertLessEqual(e["twapi"]["ukupno"], c["expand2_twapi_usd"], e)
        self.assertLessEqual(e["openai"]["ukupno"], c["expand2_openai_usd"], e)
        self.assertLessEqual(e["dan"]["twapi_ukupno"], c["day_twapi_usd"], e)
        self.assertLessEqual(e["dan"]["openai_ukupno"], c["day_openai_usd"], e)
        line = discover.estimate2_line(e)
        self.assertIn("500 → 800 računa (+300), prag 30k", line)
        self.assertIn("uz strop 25,00 $", line)
        self.assertIn("uz strop 8,00 $", line)
        self.assertIn("/ 2,00 $ twitterapi", line)
        self.assertIn("/ 0,60 $ OpenAI", line)
        self.assertIn("Pretpostavka", line)
        # even every account at the full depth (the most it can be) stays under the twitterapi cap
        full = 300 * (180 + 300 - 100) * 0.00015 + e["twapi"]["proba"] + e["twapi"]["otkrivanje"]
        self.assertLessEqual(full, c["expand2_twapi_usd"])


class Reconsider(Base):
    """The stored candidates first: nothing of discovery is paid again."""

    def setUp(self):
        super().setUp()
        owner_file(self)
        wave1_done(self.con)
        # refused by the first wave only for the old threshold: 30k-100k (four of them), one under 30k
        for k, fol in enumerate((90_000, 70_000, 50_000, 35_000)):
            stored(self.con, f"mid{k + 1}", fol)
        stored(self.con, "small", 20_000)
        stored(self.con, "promo1", 60_000, why="promo / bot opis", bio="DM for promo, giveaway every day")
        stored(self.con, "lonely", 60_000, nf=0)                       # nobody of ours follows it: not probed
        stored(self.con, "big1", 400_000, why=None, status="spreman")   # ready then, never probed (no room)
        self.posts = {"mid1": {"h": 2}, "mid2": {"h": 4}, "mid3": {"h": 8},
                      "mid4": {"h": 2, "text": "good morning frens, coffee time"}, "big1": {"h": 1}}
        self.assertTrue(discover.record_order2(self.con, cfg(), NOW, lambda *_: None))

    def test_refused_only_for_100k_are_added_without_new_discovery_spend(self):
        fx = FakeX2(posts=self.posts)
        logs = []
        c = cfg(expand_n=6)                                             # 3 measured + room for 3
        out = discover.step2(self.con, c, NOW, fx, logs.append)
        self.assertEqual((out["step"], out["dodano"], out["cap"]), ("gotovo", 3, None))
        st = dict(self.con.execute("SELECT handle, status FROM disc").fetchall())
        why = dict(self.con.execute("SELECT handle, why FROM disc").fetchall())
        # the most regular market accounts first: big1 (a post an hour), mid1, mid2; mid3 passed but the ceiling is 6
        self.assertEqual([h for h in ("big1", "mid1", "mid2", "mid3") if st[h] == "dodan"], ["big1", "mid1", "mid2"])
        self.assertEqual(st["mid3"], "probano")
        self.assertIn("tržišnih objava", why["mid4"])                    # the same other filters
        self.assertEqual((st["small"], why["small"]), ("odbijen", "ispod 30k pratitelja"))   # the new threshold
        self.assertEqual((st["promo1"], why["promo1"]), ("odbijen", "promo / bot opis"))      # not only the threshold
        self.assertEqual(st["lonely"], "spreman")
        acc = dict(self.con.execute("SELECT handle, source FROM accounts WHERE status = 'aktivan'").fetchall())
        self.assertEqual({h: s for h, s in acc.items() if s == "prosirenje2"},
                         {"big1": "prosirenje2", "mid1": "prosirenje2", "mid2": "prosirenje2"})
        self.assertEqual(self.con.execute("SELECT followers FROM accounts WHERE handle = 'mid2'").fetchone()[0], 70_000)
        self.assertEqual(len(racuni.active(self.con, include_new=True)), 6)
        # nothing of discovery was asked again: only the probe pages, all under the second wave's cap
        urls = {u for u, _p in fx.calls}
        self.assertEqual(urls, {twapi.URL})
        self.assertNotIn(twapi.FOLLOWINGS_URL, urls)
        self.assertNotIn(xapi.USER_SEARCH_URL, urls)
        self.assertNotIn(twapi.USER_URL, urls)
        self.assertEqual(set(self.con.execute("SELECT phase, what FROM spend").fetchall()), {("prosirenje2", "proba")})
        sp = discover.phase_spend(self.con)
        self.assertGreater(sp["2. val: proba"], 0)
        self.assertNotIn("2. val: otkrivanje", sp)
        self.assertEqual(store.spent(self.con, "twitterapi", "prosirenje"), 0)
        s2 = store.kv_json(self.con, "otkrivanje2")
        self.assertEqual((s2["step"], s2["krug"], s2["ponovno"]), ("gotovo", 1, 6))   # mid1-4, small, lonely
        self.assertTrue(any("otkrivanje 2. vala gotovo: ponovno razmotreno 6" in x and "bez novog otkrivanja" in x
                            for x in logs), logs)
        self.assertEqual(discover.step2(self.con, c, NOW + 60, fx, logs.append)["dodano"], 0)   # done stays done
        self.assertEqual(self.con.execute("SELECT note FROM accounts WHERE handle = 'mid1'").fetchone()[0][:26],
                         "otkriven, 2. val 30k+ (pra")

    def test_normal_discovery_only_while_under_the_ceiling(self):
        fx = FakeX2(posts=dict(self.posts, reg1={"h": 3}, reg2={"h": 5}))
        logs = []
        c = cfg(expand_n=9, disc_mention_lookups=0)                     # the stored ones (4 pass) do not fill 9
        out = discover.step2(self.con, c, NOW, fx, logs.append)
        self.assertEqual(out["step"], "gotovo")
        self.assertEqual(store.kv_json(self.con, "otkrivanje2")["krug"], 2)
        self.assertTrue(any("novo otkrivanje" in x for x in logs))
        fol = [p["userName"] for u, p in fx.calls if u == twapi.FOLLOWINGS_URL]
        self.assertNotIn("a1", fol)                                      # the first wave read its followings
        self.assertTrue({"a2", "a3", "big1", "mid1"} <= set(fol), fol)
        self.assertEqual({p.get("cursor") for u, p in fx.calls if u == twapi.FOLLOWINGS_URL}, {""})   # one page each
        self.assertEqual({ph for (ph,) in self.con.execute("SELECT DISTINCT phase FROM spend")}, {"prosirenje2"})
        self.assertGreater(discover.phase_spend(self.con)["2. val: otkrivanje"], 0)
        new = [h for (h,) in self.con.execute("SELECT handle FROM accounts WHERE source = 'prosirenje2' AND handle "
                                              "LIKE 'reg%'")]
        self.assertEqual(len(new), 2, new)                                # found by the new discovery, up to the ceiling
        self.assertEqual(len(racuni.active(self.con, include_new=True)), 9)
        self.assertTrue(any("otkrivanje 2. vala gotovo" in x and "novo otkrivanje" in x for x in logs))

    def test_seed_accounts_refused_only_for_100k_are_measured_again_from_what_is_stored(self):
        for h, fol, why in (("seed60k", 60_000, "ispod 100k pratitelja (60,000)"),
                            ("seed20k", 20_000, "ispod 100k pratitelja (20,000)"),
                            ("gone", 90_000, "X: User is suspended")):
            self.con.execute("INSERT INTO accounts (handle, status, source, category, followers, why) VALUES (?, 'odbijen', "
                             "'sjeme', 'ta', ?, ?)", (h, fol, why))
        self.con.commit()
        fx = FakeX2(posts=self.posts)
        logs = []
        discover.step2(self.con, cfg(expand_n=5), NOW, fx, logs.append)
        acc = {h: (st, src) for h, st, src in self.con.execute("SELECT handle, status, source FROM accounts")}
        self.assertEqual(acc["seed60k"], ("aktivan", "prosirenje2"))               # 30k+ now; the wave's depth and caps
        self.assertEqual(acc["seed20k"], ("odbijen", "sjeme"))                     # still under the threshold
        self.assertEqual(acc["gone"], ("odbijen", "sjeme"))                        # refused for another reason
        self.assertIn("prije: sjeme", self.con.execute("SELECT note FROM accounts WHERE handle = 'seed60k'").fetchone()[0])
        self.assertTrue(any("1 računa iz baze" in x and "@seed60k" in x for x in logs), logs)
        self.assertNotIn(twapi.USER_URL, {u for u, _p in fx.calls})                # from the stored profile
        self.assertEqual(len(racuni.active(self.con, include_new=True)), 5)        # it counts for the ceiling

    def test_the_second_waves_cap_stops_discovery_cleanly(self):
        store.kv(self.con, "prosirenje2", {"twapi_usd": 0.007, "openai_usd": 1})   # two probe pages fit, the third not
        logs = []
        out = discover.step2(self.con, cfg(expand_n=9), NOW, FakeX2(posts=self.posts), logs.append)
        self.assertIn("strop twitterapi (prosirenje2) dosegnut", out["cap"])
        self.assertEqual(out["step"], "gotovo")
        self.assertLessEqual(store.spent(self.con, "twitterapi", "prosirenje2"), 0.007 + 1e-9)
        self.assertEqual(store.spent(self.con, "twitterapi", "prosirenje"), 0)            # not on the first wave's cap
        self.assertEqual(store.left(self.con, "twapi", "prosirenje", NOW, cfg()), 40.0)
        self.assertEqual(out["dodano"], 2)                                                 # what was probed is used
        self.assertTrue(any("otkrivanje 2. vala gotovo" in x and "strop" in x for x in logs))


class Depth2(Base):
    """The second wave's accounts: their own depth and their own caps, next to the first wave's."""

    def setUp(self):
        super().setUp()
        owner_file(self)
        for k in ("pilot_twapi_done", "pilot_openai_done", "prvi_izracun"):
            store.kv(self.con, k, "1")
        wave1_done(self.con, n=1)
        self.con.execute("INSERT INTO accounts (handle, status, source, category, regularity) VALUES ('n1', 'aktivan', "
                         "'prosirenje2', 'ta', 3)")
        self.con.commit()
        self.assertTrue(discover.record_order2(self.con, cfg(), NOW, lambda *_: None))
        store.kv(self.con, "otkrivanje2", {"step": "gotovo"})
        self.con.commit()

    def test_12_months_and_300_market_posts_for_the_second_wave_only(self):
        c = cfg()
        u1 = fetch.units_left(self.con, fetch.cfg_for(self.con, c, "a1"), "a1", NOW)
        u2 = fetch.units_left(self.con, fetch.cfg_for(self.con, c, "n1"), "n1", NOW)
        months = lambda us: {u[0][3:10] for u in us if u[0].startswith("mj:")}   # noqa: E731
        self.assertEqual((len(months(u1)), len(months(u2))), (18, 12))
        self.assertEqual((u1[0][0], u2[0][0]), ("zadnjih", "zadnjih"))             # the last 200 posts for both
        fx = FakeX2(posts={"a1": {"h": 1}, "n1": {"h": 1}})
        r = fetch.backfill(self.con, c, NOW, fx, lambda *_: None, ph="dan", handles=["a1", "n1"])
        self.assertEqual(r["left"], 0)
        self.assertEqual(self.con.execute("SELECT n FROM fetch_log WHERE handle = 'n1' AND unit = 'zadnjih'")
                         .fetchone()[0], 200)
        d1, d2 = fetch.depth(self.con, "a1"), fetch.depth(self.con, "n1")
        self.assertTrue(300 <= d2 < 300 + 20, d2)                                  # stops at 300 (a page at most over)
        self.assertGreaterEqual(d1, 500)                                           # the first wave's depth as before
        full = {h for (h,) in self.con.execute("SELECT DISTINCT handle FROM fetch_log WHERE phase = 'dubina_puna'")}
        self.assertEqual(full, {"a1", "n1"})
        self.assertEqual(fetch.units_left(self.con, fetch.cfg_for(self.con, c, "n1"), "n1", NOW), [])
        oldest = self.con.execute("SELECT MIN(ts) FROM tweets WHERE handle = 'n1'").fetchone()[0]
        self.assertGreater(oldest, NOW - 366 * D)

    def test_history_under_each_waves_own_cap_then_the_daily_cap(self):
        # the second wave's cap: its account's newest 3 pages and one monthly window fit, the next window does not
        c = cfg(last_pages=3, months=2, wave2_last_pages=3, wave2_months=2, expand2_twapi_usd=0.012)
        store.kv(self.con, "prosirenje2", {"twapi_usd": 0.012, "openai_usd": 1})
        logs = []
        fx = FakeX2(posts={"a1": {"h": 1}, "n1": {"h": 1}})
        r = run._deep(self.con, c, NOW, fx, logs.append, time.time() + 60)
        self.assertIsNone(r["cap"])                                                # the first wave: its cap is far
        self.assertEqual(r["left"], 0)
        self.assertIn("strop twitterapi (prosirenje2)", r["val2"]["cap"])          # the second: stopped at ITS cap
        self.assertLessEqual(store.spent(self.con, "twitterapi", "prosirenje2"), 0.012 + 1e-9)
        self.assertGreater(store.spent(self.con, "twitterapi", "prosirenje"), 0.012)
        ph = dict(self.con.execute("SELECT handle, GROUP_CONCAT(DISTINCT phase) FROM fetch_log WHERE phase LIKE "
                                   "'prosirenje%' GROUP BY handle").fetchall())
        self.assertEqual(ph, {"a1": "prosirenje", "n1": "prosirenje2"})
        self.assertTrue(any("2. val proširenja: strop twitterapi" in x and "dnevni strop" in x for x in logs), logs)
        self.assertTrue(store.kv(self.con, "prosirenje2_strop_twapi"))
        self.assertIsNone(store.kv(self.con, "prosirenje_strop_twapi"))
        self.assertTrue(store.kv(self.con, "prosirenje_dubina_gotova"))
        run._deep(self.con, c, NOW, fx, logs.append, time.time() + 60)             # the rest under the daily cap
        self.assertGreater(store.spent(self.con, "twitterapi", "dan"), 0)
        self.assertLessEqual(store.spent(self.con, "twitterapi", "prosirenje2"), 0.012 + 1e-9)
        self.assertTrue(store.kv(self.con, "prosirenje2_dubina_gotova"))

    def test_history_classification_under_each_waves_own_cap(self):
        for k in range(60):
            self.con.execute("INSERT INTO tweets (id, handle, ts, text, src, fetched_ts, kw) VALUES (?,?,?,?,?,?,1)",
                             (f"h{k}", "n1" if k % 3 else "a1", NOW - (k + 2) * D, "btc up bullish", "mj:x", NOW))
        self.con.commit()
        self.assertEqual(len(classify.pending(self.con, 100, which="povijest", wave=2)), 40)
        self.assertEqual(len(classify.pending(self.con, 100, which="povijest", wave=1)), 20)
        c = cfg(expand2_openai_usd=0.012, cls_workers=1)
        store.kv(self.con, "prosirenje2", {"twapi_usd": 1, "openai_usd": 0.012})
        logs = []
        out = run._classify_order(self.con, c, NOW, logs.append, time.time() + 60, fake_llm())
        self.assertIsNone(out["povijest"]["cap"])                                  # the first wave's 20: all done
        self.assertEqual(out["povijest"]["batches"], 1)
        self.assertIn("strop OpenAI (prosirenje2)", out["povijest2"]["cap"])
        self.assertTrue(any("2. val proširenja: strop OpenAI" in x and "dnevnim stropom" in x for x in logs))
        self.assertLessEqual(store.spent(self.con, "openai", "prosirenje2"), 0.012 + 1e-9)
        self.assertEqual(store.spent(self.con, "openai", "prosirenje"), 0.002)     # one request, on its own cap
        self.assertGreater(store.spent(self.con, "openai", "dan"), 0)              # the rest under the daily cap
        self.assertEqual(out["povijest2_dan"]["batches"], 1)
        self.assertTrue(store.kv(self.con, "prosirenje2_strop_openai"))
        self.assertIsNone(store.kv(self.con, "prosirenje_strop_openai"))

    def test_krug_records_the_second_order_then_works_under_its_caps(self):
        # the state right after the deploy: the first wave done, the second order not recorded yet
        self.con.execute("DELETE FROM accounts WHERE handle = 'n1'")
        self.con.execute("DELETE FROM kv WHERE key IN ('nalog_prosirenje2', 'prosirenje2', 'procjena2', 'otkrivanje2')")
        self.con.execute("DELETE FROM runs WHERE kind = 'nalog_prosirenje2'")
        racuni.seed(self.con, NOW)                                      # the pilot's seed accounts are measured too
        self.con.commit()
        stored(self.con, "mid1", 60_000, nf=1)
        self.con.execute("INSERT OR IGNORE INTO disc_edge VALUES ('zz', 'mid1', 'follow')")
        self.con.commit()
        logs = []
        room = len(racuni.active(self.con, include_new=True)) + 1       # the ceiling leaves room for one account
        c = cfg(expand_n=room, months=1, last_pages=1, wave2_months=1, wave2_last_pages=1, krug_s=600)
        fx = FakeX2(posts={"mid1": {"h": 2}, "a1": {"h": 6}})
        with mock.patch.object(store, "config", lambda cfg=None: c):
            out = run.krug(NOW, logs.append, get=fx, call=fake_llm(), budget_s=600, refresh_prices=False)
        i_order = next(k for k, x in enumerate(logs) if "2. val proširenja po nalogu vlasnika" in x)
        i_est = next(k for k, x in enumerate(logs) if "procjena 2. vala (prije troška" in x)
        i_start = next(k for k, x in enumerate(logs) if "2. val: počinje od spremljenih kandidata" in x)
        self.assertTrue(i_order < i_est < i_start, (i_order, i_est, i_start))     # the estimate before its first paid call
        self.assertEqual(out["otkrivanje2"]["dodano"], 1)
        self.assertEqual(self.con.execute("SELECT source, status FROM accounts WHERE handle = 'mid1'").fetchone(),
                         ("prosirenje2", "aktivan"))
        self.assertEqual({p for (p,) in self.con.execute("SELECT phase FROM fetch_log WHERE handle = 'mid1' AND phase "
                                                         "NOT IN ('pokriveno', 'dubina_puna')")}, {"prosirenje2"})
        self.assertGreater(store.spent(self.con, "openai", "prosirenje2"), 0)      # its history, on its own cap
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM runs WHERE kind = 'nalog_prosirenje2'").fetchone()[0], 1)
        with mock.patch.object(store, "config", lambda cfg=None: c):
            run.krug(NOW + 700, logs.append, get=fx, call=fake_llm(), budget_s=600, refresh_prices=False)
        self.assertEqual(sum(1 for x in logs if "2. val proširenja po nalogu vlasnika" in x), 1)   # once


class Adam(Base):
    """The owner's "https://x.com/Adam_Tehc": confirmed, the other candidates off the waiting list."""

    def setUp(self):
        super().setUp()
        self.own = owner_file(self)
        for h in ("a1", "a2", "a3"):
            self.con.execute("INSERT INTO accounts (handle, status, source, category, added_ts) VALUES (?, 'aktivan', "
                             "'sjeme', 'ta', 1)", (h,))
        self.con.commit()
        discover.step(self.con, cfg(expand_n=4, disc_probe_max=5), NOW, FakeX2(), lambda *_: None)
        # the server's state: the placeholder waits, three candidates, the best one measured in the meantime
        self.assertEqual(self.con.execute("SELECT status FROM accounts WHERE handle = ?", (f"?{discover.ADAM}",))
                         .fetchone()[0], "needs_owner_confirm")
        self.assertEqual(self.con.execute("SELECT source FROM accounts WHERE handle = 'KobeissiLetter'").fetchone()[0],
                         "vlasnik_kandidat")

    def confirm(self):
        with open(self.own, "w", encoding="utf-8") as f:
            json.dump({"potvrdi": {discover.ADAM: "Adam_Tehc"}}, f)
        logs = []
        racuni.seed(self.con, NOW, self.own, log=logs.append)
        return logs

    def test_the_repo_file_names_adam_tehc(self):
        with open(os.path.join(ROOT, "makroinf", "racuni_vlasnik.json"), encoding="utf-8") as f:
            own = json.load(f)
        self.assertEqual(own["potvrdi"], {discover.ADAM: "Adam_Tehc"})
        self.assertEqual(own["makni"], [])
        self.assertIn("adam_tehc", racuni.OWNER_CONFIRMED)

    def test_confirmed_others_dropped_and_the_measured_candidate_stays_on_its_own_merit(self):
        logs = self.confirm()
        acc = {h: (st, src, own) for h, st, src, own in self.con.execute("SELECT handle, status, source, owner_seed "
                                                                          "FROM accounts")}
        self.assertEqual(acc["Adam_Tehc"], ("novo", "vlasnik", 1))
        self.assertNotIn(f"?{discover.ADAM}", acc)                                  # nobody waits for him any more
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM accounts WHERE status = 'needs_owner_confirm'")
                         .fetchone()[0], 0)
        cand = {x["handle"]: x["status"] for x in racuni.candidates(self.con) if x["for_name"] == discover.ADAM}
        self.assertEqual(cand, {"KobeissiLetter": "odbijen", "AdamBLiv": "odbijen", "adamscochran": "odbijen"})
        self.assertEqual([x for x in report.data(con=self.con)["candidates"] if x["status"] == "needs_owner_confirm"], [])
        # the candidate measured until his answer: a normal account now (1,5 M followers, active, market posts)
        self.assertIsNone(discover.normal_verdict(self.con, cfg(), "KobeissiLetter", NOW))
        self.assertEqual(acc["KobeissiLetter"], ("aktivan", "prosirenje", 0))
        self.assertTrue(any("vlasnik potvrdio @Adam_Tehc" in x and "@KobeissiLetter ostaje kao običan račun" in x
                            for x in logs), logs)
        self.assertEqual(self.confirm(), [])                                         # settled once
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM accounts WHERE handle = 'Adam_Tehc'").fetchone()[0], 1)

    def test_the_measured_candidate_goes_when_it_does_not_pass_on_its_own(self):
        self.con.execute("UPDATE disc SET market_share = 0.05 WHERE handle = 'KobeissiLetter'")
        self.con.commit()
        logs = self.confirm()
        st, why = self.con.execute("SELECT status, why FROM accounts WHERE handle = 'KobeissiLetter'").fetchone()
        self.assertEqual(st, "uklonjen")
        self.assertIn("sam ne prolazi uobičajene filtre: tržišnih objava 5%", why)
        self.assertTrue(any("@KobeissiLetter maknut" in x for x in logs), logs)
        self.assertNotIn("KobeissiLetter", [h for h, _c, _s in racuni.active(self.con, include_new=True)])

    def test_tracked_whatever_his_followers_and_never_replaced_by_candidates(self):
        self.confirm()
        c = cfg()
        fx = FakeX2(small={"Adam_Tehc"})                                             # 5,000 followers: under 30k
        racuni.resolve(self.con, c, NOW, fx, lambda *_: None)
        self.assertEqual(self.con.execute("SELECT status, followers, why FROM accounts WHERE handle = 'Adam_Tehc'")
                         .fetchone(), ("aktivan", 5_000, "vlasnikov izbor, ispod 30k pratitelja"))
        self.assertIn("Adam_Tehc", [h for h, _s in racuni.by_regularity(self.con)])   # in the daily fetch
        # an ordinary account with the same followers is refused by the new threshold
        self.con.execute("INSERT INTO accounts (handle, status, source, owner_seed) VALUES ('tiny5k', 'novo', 'sjeme', 0)")
        self.con.execute("DELETE FROM profile_d")
        racuni.resolve(self.con, c, NOW, FakeX2(small={"Adam_Tehc", "tiny5k"}), lambda *_: None)
        self.assertEqual(self.con.execute("SELECT status, why FROM accounts WHERE handle = 'tiny5k'").fetchone(),
                         ("odbijen", "ispod 30k pratitelja (5,000)"))
        self.assertEqual(self.con.execute("SELECT status FROM accounts WHERE handle = 'Adam_Tehc'").fetchone()[0],
                         "aktivan")
        # X says the account is gone: no candidates are searched for a handle he gave himself
        self.con.execute("DELETE FROM profile_d")
        logs = []
        fx = FakeX2(suspended={"Adam_Tehc"})
        racuni.resolve(self.con, c, NOW, fx, logs.append)
        self.assertTrue(any("vlasnikov potvrđeni račun @Adam_Tehc nije dostupan" in x for x in logs), logs)
        self.assertEqual([x for x in racuni.candidates(self.con) if x["status"] == "needs_owner_confirm"], [])

    def test_the_other_adam_candidates_become_ordinary_candidates_of_the_second_wave(self):
        self.confirm()
        store.kv(self.con, "nalog_prosirenje", {"id": "x"})
        self.assertEqual(discover._reconsider(self.con, cfg(), NOW), 1)             # "tiny" (20k) of the first wave
        st = dict(self.con.execute("SELECT handle, status FROM disc").fetchall())
        why = dict(self.con.execute("SELECT handle, why FROM disc").fetchall())
        self.assertEqual(st["AdamBLiv"], "probano")                                  # 150k, charts, market posts
        self.assertEqual((st["adamscochran"], why["adamscochran"]), ("odbijen", "opis nije kripto / makro"))
        self.assertEqual(st["KobeissiLetter"], "dodan")


class Hub800(Base):
    """800 accounts on the public hub and in the app: paged, light, every account reachable, all in the sitemap."""

    N, RANKED = 800, 230

    def setUp(self):
        super().setUp()
        from ui import public
        self.public = public
        public._cache.clear()
        self.addCleanup(public._cache.clear)
        for p in (mock.patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://example.com",
                                               "KOL_DB": os.path.join(self.tmp.name, "kol.db")}),
                  mock.patch.object(web, "STAMP_S", 0)):
            p.start()
            self.addCleanup(p.stop)
        web._FRAG.clear()
        web._SEEN["v"] = None
        self.addCleanup(web._FRAG.clear)
        self.now = int(time.time())
        scores = {}
        for k in range(self.N):
            h = f"acc{k:03d}"
            self.con.execute("INSERT INTO accounts (handle, name, category, status, followers, source) VALUES (?,?,?,?,?,?)",
                             (h, f"Account {k}", "makro" if k % 2 else "ta", "aktivan", 30_000 + k * 100,
                              "prosirenje2" if k >= 500 else "prosirenje"))
            o = outs(8 + k % 5, 4, h) if k < self.RANKED else outs(1, 1, h)
            scores[h] = score.account(o, len(o), {}, 0, 0.5)
        self.con.executemany("INSERT INTO scores VALUES (?,?,?,?)",
                             [(h, "v", self.now, json.dumps(s, ensure_ascii=False)) for h, s in scores.items()])
        store.kv(self.con, "summary", {"ts": self.now, "rank": score.rank(scores), "episodes": 3000,
                                       "outcomes": {"hit": 2000, "miss": 900, "flat": 100}})
        self.con.commit()
        self.flag(settings.MAKROINF_JAVNO, "live")

    def get(self, path):
        code, raw, _ct = self.public.route(path)
        return code, raw.decode()

    @staticmethod
    def handles(html, prefix):
        return re.findall(re.escape(prefix) + r"(acc\d{3})[\"']", html)

    def test_public_hub_is_paged_light_and_complete(self):
        v = web.view(fresh=False)
        self.assertEqual((len(v["ranked"]), len(v["few"]), mpub.hub_pages(v)), (self.RANKED, self.N - self.RANKED, 8))
        code, hub = self.get("/macro-influencers")
        self.assertEqual(code, 200)
        main = hub.split("<main", 1)[1].split("</main>", 1)[0]
        first = self.handles(main, 'href="/macro-influencer/')
        self.assertEqual(len(first), 100)                                           # not 800 rows on a phone
        self.assertIn(f"Ranked accounts · {self.RANKED}", main)
        self.assertIn("Accounts 1–100 of 800 · Page 1 of 8", main)
        self.assertIn('<a rel=next href="/macro-influencers/2">Next 100 accounts →</a>', main)
        self.assertNotIn("rel=prev", main)
        self.assertIn("<b>800</b>accounts tracked", main)
        self.assertIn("How we measure", main)                                       # page 1 keeps the method
        self.assertLess(len(hub.encode()), 400_000)
        self.assertNotIn("noindex", hub)
        self.assertEqual(hub.count('"@type": "ListItem"'), 100)
        self.assertIn('"numberOfItems": 800', hub)
        seen, sizes = list(first), [len(hub.encode())]
        for p in range(2, 9):
            code, page = self.get(f"/macro-influencers/{p}")
            self.assertEqual(code, 200, p)
            m = page.split("<main", 1)[1].split("</main>", 1)[0]
            hs = self.handles(m, 'href="/macro-influencer/')
            self.assertEqual(len(hs), 100, p)
            self.assertIn(f"Accounts {(p - 1) * 100 + 1}–{p * 100} of 800 · Page {p} of 8", m)
            self.assertIn(f'<link rel=canonical href="https://example.com/macro-influencers/{p}">', page)
            self.assertIn(f'hreflang=hr href="https://example.com/hr/makro-influenceri/{p}"', page)
            self.assertIn(f"page {p}", page.split("<title>", 1)[1].split("</title>", 1)[0])
            self.assertNotIn("noindex", page)
            self.assertNotIn("How we measure</h2>", m)                             # only the list on the next pages
            prev = "/macro-influencers#rank" if p == 2 else f"/macro-influencers/{p - 1}"
            self.assertIn(f'<a rel=prev href="{prev}">', m)
            self.assertEqual(f'<a rel=next href="/macro-influencers/{p + 1}">' in m, p < 8)
            seen += hs
            sizes.append(len(page.encode()))
        self.assertEqual(len(seen), 800)
        self.assertEqual(set(seen), {f"acc{k:03d}" for k in range(800)})            # every account on exactly one page
        self.assertEqual(seen[:self.RANKED], [r["handle"] for r in v["ranked"]])    # the ranked ones first, in order
        self.assertLess(max(sizes), 400_000)
        # page 3 carries the end of the ranking (numbered on) and the start of the ones still collecting
        p3 = self.get("/macro-influencers/3")[1]
        self.assertIn("<td class='mut mr-rk'>201</td>", p3)
        self.assertIn(f"Still collecting evidence · {self.N - self.RANKED}", p3)
        self.assertEqual(self.get("/macro-influencers/9")[0], 404)                  # past the last page
        code, hr = self.get("/hr/makro-influenceri/2")
        self.assertEqual(code, 200)
        self.assertIn("Računi 101–200 od 800 · Stranica 2 od 8", hr)
        self.assertIn('<a rel=next href="/hr/makro-influenceri/3">Sljedećih 100 računa →</a>', hr)
        self.assertEqual(len(self.handles(hr, 'href="/hr/makro-influencer/')), 100)
        for path in ("/macro-influencers/3", "/hr/makro-influenceri/8", "/macro-influencers"):
            self.assertTrue(web._is_ours(path), path)                               # dropped after every scoring
        self.assertIsNone(mpub.match("/macro-influencers/1"))                       # page 1 is the hub itself
        self.assertIsNone(mpub.match("/macro-influencers/x"))

    def test_sitemap_has_every_account_and_every_hub_page(self):
        sm = self.get("/sitemap.xml")[1]
        day = time.strftime("%Y-%m-%d", time.gmtime(self.now))
        for k in range(self.N):
            self.assertIn(f"/macro-influencer/acc{k:03d}</loc><lastmod>{day}", sm)
            self.assertIn(f"/hr/makro-influencer/acc{k:03d}</loc>", sm)
        for p in range(2, 9):
            self.assertIn(f"https://example.com/macro-influencers/{p}</loc>", sm)
            self.assertIn(f"https://example.com/hr/makro-influenceri/{p}</loc>", sm)
        self.assertNotIn("/macro-influencers/9<", sm)
        self.assertEqual(web.sitemap_count(), 800)
        self.assertEqual(len([u for u in mpub.urls() if u[0].startswith("/macro-influencer/")]), 800)
        code, prof = self.get("/macro-influencer/acc799")                           # a second-wave account's own page
        self.assertEqual(code, 200)
        self.assertNotIn("noindex", prof)

    def test_app_list_is_paged_too(self):
        tab = web.tab_html()
        self.assertEqual(len(self.handles(tab, "href='/kol-makro/")), 100)
        self.assertIn(f"Najtočniji · {self.RANKED}", tab)
        self.assertIn("Računi 1–100 od 800 · stranica 1 od 8", tab)
        self.assertIn("<a href='/kol-makro?str=2'>Sljedećih 100 →</a>", tab)
        seen = self.handles(tab, "href='/kol-makro/")
        for p in range(2, 9):
            _t, body = web.list_page(qs={"str": str(p)})
            hs = self.handles(body, "href='/kol-makro/")
            self.assertEqual(len(hs), 100, p)
            self.assertIn(f"stranica {p} od 8", body)
            seen += hs
        self.assertEqual(set(seen), {f"acc{k:03d}" for k in range(800)})
        self.assertEqual(len(seen), 800)
        _t, last = web.list_page(qs={"str": "99"})                                   # past the end: the last page
        self.assertIn("stranica 8 od 8", last)
        self.assertNotIn("Sljedećih", last)
        _t, bad = web.list_page(qs={"str": "x' OR 1=1"})                             # a broken value: page 1
        self.assertIn("stranica 1 od 8", bad)


if __name__ == "__main__":
    unittest.main()
