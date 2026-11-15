"""15.11. navečer (vlasnik: "Bravo. Objavi. Neka Google sve indeksira, pa nek se podaci osvježavaju. I želim veliku
listu makroinfluencera, sve ih dodati u bazu i sve ih pratiti na dnevnom nivou ... pratiti ih 300, 400, 500 ovih
najredovitijih. Ima i ovaj Marty Party ... Ima onaj Adam ... Interpretirati, klasterizirati pa reći 55 % influencera
je bullish, 45 % bearish, što znači da je neizvjesno ... prikazati iz čega su izvučeni ti podaci i tablice"), offline:

  - Google: every profile indexable (no noindex, the honest label stays) and in the sitemap with lastmod; the hub too
  - the expansion forced BY THE OWNER'S ORDER: recorded once (kv, runs, log line), the quality gate overridden, the
    DEMO input of the index NOT opened by it; the estimate logged before any money is spent
  - discovery: followings (paged), user search, the owner's seeds (Marty Party, Adam: 3 candidates, the clearly best
    one included), filters (100k+, active in 30 days, >= 20 % market posts, no promo / bot, no exchange), the most
    regular added first
  - depth: the last 200 posts (the probe page reused), monthly windows (first halves first), up to depth_posts market
    posts, windows the newest posts cover not bought
  - budget caps stop each phase cleanly: discovery, deep history, history classification, daily fetch, daily
    classification, topics
  - the daily fetch: every active account once a day since its newest post, deadline-safe, inactive ones weekly
  - the mood: shares, weighted by accuracy with the cluster cap, the verdict thresholds (55 / 45 = neizvjesno), changes
  - topics: validated (unknown ids, < 2 posts, max 5), inside the daily cap, the lexicon without a model
  - "Iz čega je izvučeno" tables in the app and on the hub; the library filters; no forbidden content anywhere

    python3 -m unittest tests.test_makro2_offline
"""
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
from makroinf import (appviews, classify, deleted, discover, fetch, library, mood, quality, racuni, run,  # noqa: E402
                      store, teme, web, xapi)
from makroinf import index as mindex  # noqa: E402
from makroinf import public as mpub  # noqa: E402
from tests.test_makroinf_offline import NOW, Base, FakeX, fake_llm, rising  # noqa: E402
from trade import settings  # noqa: E402

D = 86400
FORBIDDEN = ("twitterapi", "openai", "gpt-", "api key", "api_key", "_KEY", "MAKROINF_DB", "DATA_DIR", "makroinf.db",
             "render", "coingecko", "trošak", "cost", " $", "usd", "wallet", "novčanik", "skriva")
ADDRESS = re.compile(r"(?<![\w/])[1-9A-HJ-NP-Za-km-z]{32,44}(?![\w])")


def user(h, fol=250_000, bio="crypto macro analyst, BTC charts", name=None, **kw):
    return {"userName": h, "name": name or h, "followers": fol, "statusesCount": 20_000, "description": bio, **kw}


FOLLOW = [user("reg1", 900_000), user("reg2", 800_000), user("reg3", 700_000), user("reg4", 600_000),
          user("reg5", 500_000), user("reg6", 400_000), user("tiny", 20_000),
          user("promo1", 300_000, "DM for promo, giveaway every day"), user("quiet", 3_000_000),
          user("chatty", 3_000_000), user("spammer", 3_000_000),   # the best scored: probed first, then rejected
          user("exch", 2_000_000, "The official account of a crypto exchange")]
POSTS = {"reg1": {"h": 1}, "reg2": {"h": 2}, "reg3": {"h": 4}, "reg4": {"h": 6}, "reg5": {"h": 12}, "reg6": {"h": 24},
         "quiet": {"h": 2, "age_d": 60}, "chatty": {"h": 2, "text": "good morning frens, coffee time"},
         "spammer": {"h": 2, "text": "BTC giveaway! airdrop for everyone, use code MOON"},
         "KobeissiLetter": {"h": 3, "text": "BTC and market data: inflation, rates and liquidity statistics"},
         "AdamBLiv": {"h": 8}, "adamscochran": {"h": 10}}
PROFILES = {"KobeissiLetter": user("KobeissiLetter", 1_500_000, "Commentary on global capital markets: data and "
                                   "statistics", name="The Kobeissi Letter"),
            "AdamBLiv": user("AdamBLiv", 150_000, "Bitcoin author, charts", name="Adam Livingston"),
            "adamscochran": user("adamscochran", 280_000, "Partner at a venture firm", name="Adam Cochran"),
            "martypartymusic": user("martypartymusic", 600_000, "Crypto and macro, markets", name="Marty Party")}


class FakeX2(FakeX):
    """FakeX + followings in pages of 5 (cursor), per-handle post patterns, the owner's names' profiles, searches."""

    def __init__(self, follow=FOLLOW, posts=POSTS, profiles=PROFILES, search=(), **kw):
        super().__init__(**kw)
        self.follow, self.posts, self.profiles, self.search = list(follow), dict(posts), dict(profiles), list(search)

    def __call__(self, url, params):
        if url == twapi.FOLLOWINGS_URL:
            self.calls.append((url, dict(params)))
            p = int(params.get("cursor") or 0)
            return {"followings": self.follow[p * 5:(p + 1) * 5], "has_next_page": (p + 1) * 5 < len(self.follow),
                    "next_cursor": str(p + 1)}
        if url == xapi.USER_SEARCH_URL:
            self.calls.append((url, dict(params)))
            return {"users": [] if "Adam" in params["query"] else self.search}
        if url == twapi.USER_URL and params["userName"] in self.profiles and params["userName"] not in self.suspended:
            self.calls.append((url, dict(params)))
            return {"status": "success", "data": dict(self.profiles[params["userName"]], id="7")}
        if url == twapi.URL:
            q = params["query"]
            h = re.search(r"from:(\w+)", q).group(1)
            if h in self.posts:
                self.calls.append((url, dict(params)))
                pat = self.posts[h]
                a = int(re.search(r"since_time:(\d+)", q).group(1)) if "since_time" in q else 0
                b = int(re.search(r"until_time:(\d+)", q).group(1)) if "until_time" in q else NOW
                b = min(b, NOW - int(pat.get("age_d", 0) * D))
                page = int(params.get("cursor") or 0)
                tws = []
                for k in range(self.per_page):
                    ts = b - int(pat["h"] * 3600) * (1 + k + page * self.per_page)
                    if ts <= a:
                        break
                    tid = str(abs(hash((h, ts))) % 10 ** 15)
                    tws.append({"id": tid, "createdAt": ts, "text": pat.get("text", "BTC bullish, the cycle goes up"),
                                "lang": "en", "likeCount": 7, "author": {"userName": h},
                                "url": f"https://x.com/{h}/status/{tid}"})
                return {"tweets": tws, "has_next_page": len(tws) == self.per_page, "next_cursor": str(page + 1)}
        return super().__call__(url, params)


def cfg(**kw):
    return {**store.config(), **kw}


class Order(Base):
    """The owner's order: recorded once, the gate overridden and logged, the estimate before the money."""

    def setUp(self):
        super().setUp()
        for h in ("a1", "a2", "a3"):
            self.con.execute("INSERT INTO accounts (handle, status, source, category, added_ts) VALUES (?, 'aktivan', "
                             "'sjeme', 'ta', 1)", (h,))
        self.con.commit()

    def test_recorded_once_gate_overridden_demo_input_not(self):
        store.kv(self.con, "provjera", {"ts": 1, "passed": False, "why": "pada: ta"})
        self.assertIsNotNone(quality.gate(self.con))
        logs = []
        c = cfg(expand_n=10)
        self.assertTrue(discover.record_order(self.con, c, NOW, logs.append))
        rec = store.kv_json(self.con, "nalog_prosirenje")
        self.assertTrue(rec["provjera_nadjacana"])
        self.assertIn("pratiti ih 300, 400, 500", rec["citat"])
        self.assertIsNone(quality.gate(self.con))                                     # the order opens the expansion
        q = store.kv_json(self.con, "provjera")
        self.assertFalse(q.get("forced"))                                             # ... not the generic force
        self.assertEqual(mindex.input_state(self.con, w={}, ev={})["state"], "na_cekanju")   # DEMO input untouched
        self.assertIn("po nalogu vlasnika", logs[0])
        self.assertIn("nadjačana vlasnikovim izričitim nalogom", logs[0])
        self.assertIn("procjena proširenja (prije troška)", logs[1])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM spend").fetchone()[0], 0)   # nothing spent yet
        self.assertEqual(self.con.execute("SELECT kind FROM runs").fetchall(), [("nalog_prosirenje",)])
        caps = store.kv_json(self.con, "prosirenje")
        self.assertEqual((caps["twapi_usd"], caps["openai_usd"]), (40.0, 15.0))
        est = store.kv_json(self.con, "procjena")
        self.assertEqual(est["novih"], 7)
        self.assertGreater(est["twapi"]["ukupno"], 0)
        self.assertEqual(est["stropovi"], {"twapi": 40.0, "openai": 15.0, "dan_twapi": 1.5, "dan_openai": 0.5})
        self.assertTrue(discover.record_order(self.con, c, NOW + 60, logs.append))
        self.assertEqual(len(logs), 2)                                                # once
        self.assertFalse(discover.record_order(self.con, cfg(expand_by_order=False), NOW, logs.append))
        # a later quality check keeps the order's record
        quality.run(self.con, c, NOW, log=lambda *_: None, call=fake_llm(), write=False)
        self.assertTrue(store.kv_json(self.con, "provjera").get("nalog"))

    def test_the_estimate_of_500_accounts_fits_the_caps(self):
        c = store.config()
        e = discover.estimate(self.con, c, NOW, n_new=454)
        self.assertLessEqual(e["twapi"]["ukupno"], 40.0 * 1.25, e)          # Pretpostavka: the cap cuts the rest
        self.assertLessEqual(e["dan"]["twapi_ukupno"], c["day_twapi_usd"], e)
        self.assertLessEqual(e["dan"]["openai_ukupno"], c["day_openai_usd"], e)
        self.assertIn("procjena proširenja", discover.estimate_line(e, c))

    def test_krug_records_the_order_after_the_pilot(self):
        for k in ("pilot_twapi_done", "pilot_openai_done", "prvi_izracun"):
            store.kv(self.con, k, str(NOW - D))
        self.con.commit()
        own = os.path.join(self.tmp.name, "own.json")
        with open(own, "w") as f:
            json.dump({}, f)
        logs = []
        c = cfg(expand_n=60, disc_follow_pages=1, months=1, last_pages=1, krug_s=600)
        with mock.patch.object(racuni, "OWNER_FILE", own), mock.patch.object(store, "config", lambda cfg=None: c):
            out = run.krug(NOW, logs.append, get=FakeX2(), call=fake_llm(), budget_s=600, refresh_prices=False)
        self.assertTrue(store.kv(self.con, "nalog_prosirenje"))
        self.assertTrue(any("po nalogu vlasnika" in x for x in logs))
        self.assertTrue(any("otkrivanje gotovo" in x for x in logs), logs[-5:])
        self.assertIn("otkrivanje", out)
        self.assertGreater(store.spent(self.con, "twitterapi", "prosirenje"), 0)
        # Marty Party (the owner's seed) is measured
        self.assertEqual(self.con.execute("SELECT status, owner_seed FROM accounts WHERE handle = 'martypartymusic'")
                         .fetchone(), ("aktivan", 1))


class Discovery(Base):
    def setUp(self):
        super().setUp()
        for h in ("a1", "a2", "a3"):
            self.con.execute("INSERT INTO accounts (handle, status, source, category, added_ts) VALUES (?, 'aktivan', "
                             "'sjeme', 'ta', 1)", (h,))
        self.con.commit()
        own = os.path.join(self.tmp.name, "own.json")
        with open(own, "w") as f:
            json.dump({}, f)
        p = mock.patch.object(racuni, "OWNER_FILE", own)
        p.start()
        self.addCleanup(p.stop)
        self.own = own

    def test_followings_filters_probes_and_the_most_regular_first(self):
        fx = FakeX2()
        logs = []
        c = cfg(expand_n=7, expand_min=5, disc_probe_max=50)
        out = discover.step(self.con, c, NOW, fx, logs.append)
        self.assertEqual(out["step"], "gotovo")
        st = dict(self.con.execute("SELECT handle, status FROM disc").fetchall())
        why = dict(self.con.execute("SELECT handle, why FROM disc").fetchall())
        self.assertEqual(st["tiny"], "odbijen")
        self.assertIn("ispod 100k", why["tiny"])
        self.assertIn("promo", why["promo1"])
        self.assertIn("burza", why["exch"])
        self.assertIn("bez objave u 30 dana", why["quiet"])
        self.assertIn("tržišnih objava", why["chatty"])
        self.assertIn("promo objava", why["spammer"])
        # Adam: the clearly best one is measured (until the owner confirms), the 3 best wait for him
        cand = {x["handle"]: x["status"] for x in racuni.candidates(self.con) if x["for_name"] == discover.ADAM}
        self.assertEqual(cand, {"KobeissiLetter": "ukljucen_ceka_potvrdu", "AdamBLiv": "needs_owner_confirm",
                                "adamscochran": "needs_owner_confirm"})
        acc = dict(self.con.execute("SELECT handle, source FROM accounts WHERE status = 'aktivan'").fetchall())
        self.assertEqual(acc["KobeissiLetter"], "vlasnik_kandidat")
        # 3 + Kobeissi = 4; the 3 most regular passing candidates fill up to 7
        added = [h for (h,) in self.con.execute("SELECT handle FROM accounts WHERE source = 'prosirenje' ORDER BY "
                                                "regularity DESC, handle")]
        self.assertEqual(added, ["reg1", "reg2", "reg3"])
        self.assertEqual(self.con.execute("SELECT status FROM accounts WHERE handle = 'reg1'").fetchone()[0], "aktivan")
        self.assertTrue(any("otkrivanje gotovo" in x and "dodano 3" in x for x in logs), logs)
        # followings were read in pages (cursor), every call under the expansion phase
        pages = [p["cursor"] for u, p in fx.calls if u == twapi.FOLLOWINGS_URL and p["userName"] == "a1"]
        self.assertEqual(pages, ["", "1", "2"])
        self.assertEqual({ph for (ph,) in self.con.execute("SELECT DISTINCT phase FROM spend")}, {"prosirenje"})
        sp = discover.phase_spend(self.con)
        self.assertGreater(sp["otkrivanje"], 0)
        self.assertGreater(sp["proba"], 0)
        # the probe's posts are kept (src proba) and are the first page of the account's zadnjih later
        self.assertGreater(self.con.execute("SELECT COUNT(*) FROM tweets WHERE handle = 'reg1' AND src = 'proba'")
                           .fetchone()[0], 0)

    def test_owner_confirms_another_adam(self):
        discover.step(self.con, cfg(expand_n=4, disc_probe_max=5), NOW, FakeX2(), lambda *_: None)
        self.assertEqual(self.con.execute("SELECT status FROM accounts WHERE handle = 'KobeissiLetter'").fetchone()[0],
                         "aktivan")
        with open(self.own, "w") as f:
            json.dump({"potvrdi": {discover.ADAM: "AdamBLiv"}}, f)
        racuni.seed(self.con, NOW, self.own)
        st = dict(self.con.execute("SELECT handle, status FROM accounts").fetchall())
        self.assertEqual(st["KobeissiLetter"], "uklonjen")
        self.assertEqual(st["AdamBLiv"], "novo")
        self.assertNotIn(f"?{discover.ADAM}", st)
        self.assertEqual(self.con.execute("SELECT source, owner_seed FROM accounts WHERE handle = 'AdamBLiv'").fetchone(),
                         ("vlasnik", 1))

    def test_marty_party_seed_and_candidates_when_it_does_not_resolve(self):
        racuni.seed(self.con, NOW, self.own)
        self.assertEqual(self.con.execute("SELECT owner_seed, source, status FROM accounts WHERE handle = "
                                          "'martypartymusic'").fetchone(), (1, "vlasnik", "novo"))
        fx = FakeX2(suspended={"martypartymusic"}, search=[user("MartyPartyReal", 400_000, "crypto markets")])
        racuni.resolve(self.con, cfg(), NOW, fx, lambda *_: None)
        self.assertEqual(self.con.execute("SELECT status FROM accounts WHERE handle = 'martypartymusic'").fetchone()[0],
                         "odbijen")
        self.assertIn("MartyPartyReal", [x["handle"] for x in racuni.candidates(self.con)
                                         if x["for_name"] == "Marty Party"])

    def test_the_discovery_cap_stops_cleanly_and_selects_what_was_probed(self):
        logs = []
        c = cfg(expand_n=9, expand_twapi_usd=0.004)
        store.kv(self.con, "prosirenje", {"twapi_usd": 0.004, "openai_usd": 0.01})
        out = discover.step(self.con, c, NOW, FakeX2(), logs.append)
        self.assertIn("strop twitterapi (prosirenje)", out["cap"])
        self.assertEqual(out["step"], "gotovo")
        self.assertLessEqual(store.spent(self.con, "twitterapi", "prosirenje"), 0.004 + 1e-9)
        self.assertTrue(any("otkrivanje gotovo" in x and "strop" in x for x in logs))


class Depth(Base):
    def setUp(self):
        super().setUp()
        self.con.execute("INSERT INTO accounts (handle, status, category) VALUES ('deep', 'aktivan', 'ta')")
        self.con.commit()

    def test_last_200_reuse_the_probe_page_months_first_halves_and_the_depth_cap(self):
        fx = FakeX2(posts={"deep": {"h": 1}})
        c = cfg(last_pages=3, months=3, depth_posts=100, page_posts=20)
        discover.probe_one(self.con, c, "deep", NOW, fx, ph="dan")
        oldest_probe = self.con.execute("SELECT MIN(ts) FROM tweets WHERE src = 'proba'").fetchone()[0]
        fx.calls.clear()
        r = fetch.backfill(self.con, c, NOW, fx, lambda *_: None, ph="dan")
        self.assertEqual(r["left"], 0)
        qs = [p["query"] for u, p in fx.calls if u == twapi.URL]
        # zadnjih goes on from before the probe page: 2 more pages, not 3
        self.assertIn(f"until_time:{oldest_probe}", qs[0])
        self.assertEqual(sum(1 for q in qs if "since_time" not in q), 2)
        log = dict(self.con.execute("SELECT unit, phase FROM fetch_log WHERE handle = 'deep'").fetchall())
        self.assertEqual(self.con.execute("SELECT n FROM fetch_log WHERE unit = 'zadnjih'").fetchone()[0], 60)
        # 60 market posts from the newest pages, one month window (20) -> 80; the next one -> 100 = the cap
        fetched = [u for u, ph in log.items() if u.startswith("mj:") and ph == "dan"]
        full = [u for u, ph in log.items() if ph == "dubina_puna"]
        self.assertEqual(len(fetched), 2)
        self.assertTrue(all(u.endswith(":a") for u in fetched), fetched)          # first halves first
        self.assertTrue(full)
        self.assertGreaterEqual(fetch.depth(self.con, "deep"), 100)
        self.assertEqual(fetch.units_left(self.con, c, "deep", NOW), [])

    def test_a_window_the_newest_posts_cover_is_not_bought(self):
        fx = FakeX2(posts={"deep": {"h": 24}})          # one post a day: 3 pages = 60 days of everything
        c = cfg(last_pages=3, months=2, depth_posts=500)
        fetch.backfill(self.con, c, NOW, fx, lambda *_: None, ph="dan")
        log = dict(self.con.execute("SELECT unit, phase FROM fetch_log WHERE handle = 'deep'").fetchall())
        self.assertTrue(all(ph == "pokriveno" for u, ph in log.items() if u.startswith("mj:")), log)

    def test_the_pilot_accounts_get_their_posts_101_to_200(self):
        self.con.execute("INSERT INTO fetch_log VALUES ('deep', 'zadnjih', ?, 100, NULL, 'pilot')", (NOW - D,))
        for k in range(100):
            self.con.execute("INSERT INTO tweets (id, handle, ts, text, src, fetched_ts, kw) VALUES (?,?,?,?,?,?,1)",
                             (f"z{k}", "deep", NOW - D - k * 3600, "btc", "zadnjih", NOW - D))
        self.con.commit()
        c = cfg(months=1)
        self.assertEqual(fetch.units_left(self.con, c, "deep", NOW)[0], ("zadnjih+", None, None))
        fx = FakeX2(posts={"deep": {"h": 1}})
        fetch.backfill(self.con, cfg(months=0), NOW, fx, lambda *_: None, ph="dan")
        q = [p["query"] for u, p in fx.calls if u == twapi.URL]
        self.assertEqual(len(q), 5)
        self.assertIn(f"until_time:{NOW - D - 99 * 3600}", q[0])


class Daily(Base):
    def setUp(self):
        super().setUp()
        for k, (h, st, reg) in enumerate((("x1", "aktivan", 5), ("x2", "aktivan", 1), ("x3", "aktivan", 3),
                                          ("x4", "aktivan", None), ("x5", "aktivan", 9), ("x6", "neaktivan", 2))):
            self.con.execute("INSERT INTO accounts (handle, status, category, regularity, added_ts) VALUES "
                             "(?,?,?,?,?)", (h, st, "ta", reg, k))
            if h != "x5":   # x5: its backfill has not started yet
                self.con.execute("INSERT INTO fetch_log VALUES (?, 'zadnjih', ?, 20, NULL, 'dan')", (h, NOW - 3 * D))
                self.con.execute("INSERT INTO tweets (id, handle, ts, text, src, fetched_ts, kw) VALUES (?,?,?,?,?,?,1)",
                                 (f"o{h}", h, NOW - (40 if h == "x6" else 2) * D, "btc up", "zadnjih", NOW - 3 * D))
        self.con.execute("INSERT INTO daily_fetch VALUES ('x6', ?, 0)", (NOW - 8 * D,))
        store.kv(self.con, "pilot_twapi_done", "1")
        self.con.commit()

    def test_every_account_once_a_day_since_its_newest_post_deadline_safe(self):
        fx = FakeX2(posts={h: {"h": 6} for h in ("x1", "x2", "x3", "x4", "x6")})
        c = cfg()
        clock = iter(range(10_000, 10_100))
        with mock.patch.object(fetch.time, "time", lambda: float(next(clock))):
            r = fetch.incremental(self.con, c, NOW, fx, lambda *_: None, deadline=10_001.5)
        self.assertEqual((r["accounts"], r["left"]), (2, 3))
        done = [h for (h,) in self.con.execute("SELECT handle FROM daily_fetch WHERE ts = ?", (NOW,))]
        self.assertEqual(sorted(done), ["x1", "x3"])                          # the most regular first (x5 not started)
        r2 = fetch.incremental(self.con, c, NOW + 60, fx, lambda *_: None)
        self.assertEqual((r2["accounts"], r2["left"]), (3, 0))               # the rest, not the ones done
        self.assertEqual(r2["reaktivirano"], 1)                              # x6 asked after a week: posts again
        self.assertEqual(self.con.execute("SELECT status FROM accounts WHERE handle = 'x6'").fetchone()[0], "aktivan")
        q = [p["query"] for u, p in fx.calls if u == twapi.URL and "from:x2 " in p["query"]][0]
        self.assertIn(f"since_time:{NOW - 2 * D + 1}", q)                    # since the newest stored post
        self.assertIn("-filter:retweets", q)
        self.assertEqual(fetch.incremental(self.con, c, NOW + 3600, fx, lambda *_: None)["accounts"], 0)   # once a day
        self.assertEqual(fetch.incremental(self.con, c, NOW + D, fx, lambda *_: None)["accounts"], 5)
        self.assertEqual({p for (p,) in self.con.execute("SELECT DISTINCT phase FROM spend")}, {"dan"})

    def test_the_daily_cap_stops_the_daily_fetch(self):
        store.kv(self.con, "pilot_twapi_done", "1")
        store.kv(self.con, "pilot_openai_done", "1")
        c = cfg(day_twapi_usd=0.004)
        r = fetch.incremental(self.con, c, NOW, FakeX2(posts={h: {"h": 1} for h in ("x1", "x2", "x3", "x4")}),
                              lambda *_: None)
        self.assertIn("strop twitterapi (dan)", r["cap"])
        self.assertLessEqual(store.spent(self.con, "twitterapi", "dan", store.day(NOW)), 0.004 + 1e-9)
        self.assertGreater(r["left"], 0)


class Budget2(Base):
    def setUp(self):
        super().setUp()
        for k in ("pilot_twapi_done", "pilot_openai_done", "prvi_izracun"):
            store.kv(self.con, k, "1")
        for h in ("b1", "b2"):
            self.con.execute("INSERT INTO accounts (handle, status, category, regularity) VALUES (?, 'aktivan', 'ta', 1)",
                             (h,))
        self.con.commit()

    def test_deep_history_cap_then_the_daily_cap(self):
        c = cfg(expand_twapi_usd=0.005, last_pages=3, months=2)
        store.kv(self.con, "prosirenje", {"twapi_usd": 0.005, "openai_usd": 1})
        store.kv(self.con, "otkrivanje", {"step": "gotovo"})
        logs = []
        fx = FakeX2(posts={"b1": {"h": 1}, "b2": {"h": 1}})
        r = run._deep(self.con, c, NOW, fx, logs.append, time.time() + 60)
        self.assertIn("strop twitterapi (prosirenje)", r["cap"])
        self.assertLessEqual(store.spent(self.con, "twitterapi", "prosirenje"), 0.005 + 1e-9)
        self.assertTrue(any("ostatak povijesti" in x and "dnevni strop" in x for x in logs))
        run._deep(self.con, c, NOW, fx, logs.append, time.time() + 60)        # the rest under the daily cap
        self.assertGreater(store.spent(self.con, "twitterapi", "dan"), 0)
        self.assertTrue(any("trošak po fazi" in x for x in logs))

    def test_history_classification_cap_then_daily_and_the_daily_openai_cap(self):
        for k in range(80):
            self.con.execute("INSERT INTO tweets (id, handle, ts, text, src, fetched_ts, kw) VALUES (?,?,?,?,?,?,1)",
                             (f"h{k}", "b1" if k % 2 else "b2", NOW - (k + 2) * D, "btc up bullish", "mj:x", NOW))
        for k in range(10):
            self.con.execute("INSERT INTO tweets (id, handle, ts, text, src, fetched_ts, kw) VALUES (?,?,?,?,?,?,1)",
                             (f"d{k}", "b1", NOW - k * 3600, "btc down", "dnevno", NOW))
        self.con.commit()
        c = cfg(expand_openai_usd=0.012, day_openai_usd=0.014, cls_workers=1)
        store.kv(self.con, "prosirenje", {"twapi_usd": 1, "openai_usd": 0.012})
        logs = []
        out = run._classify_order(self.con, c, NOW, logs.append, time.time() + 60, fake_llm())
        self.assertEqual(out["dnevno"]["batches"], 1)                               # the day's posts first
        self.assertIn("strop OpenAI (prosirenje)", out["povijest"]["cap"])
        self.assertTrue(any("strop OpenAI" in x and "dnevnim stropom" in x for x in logs))
        self.assertLessEqual(store.spent(self.con, "openai", "prosirenje"), 0.012 + 1e-9)
        self.assertIn("strop OpenAI (dan)", out["povijest_dan"]["cap"])              # then the daily cap stops it
        self.assertLessEqual(store.spent(self.con, "openai", "dan", store.day(NOW)), 0.03 + 1e-9)


class Mood(unittest.TestCase):
    def test_verdict_thresholds(self):
        v = mood.verdict
        self.assertEqual(v(55, 45, 0), "neizvjesno")                      # the owner's example
        self.assertEqual(v(45, 55, 0), "neizvjesno")
        self.assertEqual(v(50, 50, 0), "neizvjesno")
        self.assertEqual(v(56, 44, 0), "blago_bik")
        self.assertEqual(v(64, 36, 0), "blago_bik")
        self.assertEqual(v(65, 35, 0), "jasno_bik")
        self.assertEqual(v(35, 65, 0), "jasno_medvjed")
        self.assertEqual(v(40, 60, 0), "blago_medvjed")
        self.assertEqual(v(3, 1, 4), "neutralno")                          # neutral is half or more
        self.assertEqual(v(0, 0, 0), "premalo")
        self.assertIn("55\u00a0/\u00a045 je neizvjesno", mood.rule_text("hr"))

    def _st(self, signs):
        return {h: {"s": s, "n": 1, "ids": [f"{h}1"], "ts": NOW} for h, s in signs.items()}

    def test_shares_weighted_and_the_cluster_cap(self):
        st = self._st({"c1": 1, "c2": 1, "c3": 1, "b1": -1, "b2": -1})
        b = mood.block(st, {}, {})
        self.assertEqual(b["broj"], {"bik": 3, "medvjed": 2, "neutralno": 0})
        self.assertAlmostEqual(b["udio"]["bik"], 0.6)
        self.assertEqual(b["presuda"], "blago_bik")
        cl = {"c1": "k", "c2": "k", "c3": "k"}                            # three look-alikes: one voice and a half
        b2 = mood.block(st, {}, cl)
        self.assertAlmostEqual(b2["udio_pond"]["bik"], 1.5 / 3.5, 6)
        self.assertEqual(b2["presuda_pond"], "blago_medvjed")
        self.assertEqual(b2["presuda"], "blago_bik")                       # the unweighted one stays
        acc = {"b1": 0.8, "b2": 0.8, "c1": 0.4, "c2": 0.4, "c3": 0.4}       # accuracy weights
        b3 = mood.block(st, acc, {})
        self.assertGreater(b3["udio_pond"]["medvjed"], 0.5)
        self.assertEqual(mood.block(self._st({"a": 1, "b": 1, "c": -1, "d": -1}), {}, {})["presuda"], "premalo")
        self.assertEqual({r["h"] for r in b["racuni"]["bik"]}, {"c1", "c2", "c3"})   # the source of the statement


class Views(Base):
    """Synthetic data end to end: mood, topics, library, app tab, public hub."""

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
        c = self.con
        c.executemany("INSERT INTO px VALUES (?,?,?,?)", [("bitcoin", "d", t, p) for t, p in rising(330, 30_000,
                                                                                                  end=self.now)])
        n = 0
        self.public_ids = set()
        for k in range(12):
            h = f"acct{k}"
            c.execute("INSERT INTO accounts (handle, name, category, status, followers) VALUES (?,?,?,?,?)",
                      (h, f"Account {k}", "makro" if k % 2 else "ta", "aktivan", 200_000 + k))
            for j, age_h in enumerate((2, 30, 7 * 24 + 6, 20 * 24)):        # 24 h, 7 d, public window, before
                n += 1
                d = "up" if (k < 7) != (j == 3) else "down"
                if k == 11:
                    d = "range"
                if k == 1 and j == 2:   # acct1: down a week ago, up now (a stance change)
                    d = "down"
                if j == 2:
                    self.public_ids.add(n)
                self.add(n, h, self.now - age_h * 3600, d, "ETH" if j == 1 and k % 3 == 0 else "BTC")
            n += 1   # one post that is no call
            c.execute("INSERT INTO tweets (id, handle, ts, text, fetched_ts, kw, macro, cls_ts, cls_v, likes, views, url, "
                      "src) VALUES (?,?,?,?,?,1,0,?,'v1',3,900,?,'zadnjih')",
                      (str(9000 + n), h, self.now - 5 * 3600, "gm, coffee and charts", self.now, self.now,
                       f"https://x.com/{h}/status/{9000 + n}"))
        c.commit()
        run.score_all(c, self.now, log=lambda *_: None)
        teme.run(c, cfg(), self.now, log=lambda *_: None, call=self.llm, force=True)

    def add(self, n, h, ts, d, asset="BTC", hz=None):
        self.con.execute("INSERT INTO tweets (id, handle, ts, text, fetched_ts, kw, macro, cls_ts, cls_v, likes, views, "
                         "url, src) VALUES (?,?,?,?,?,1,1,?,'v1',?,?,?,'mj:x')",
                         (str(n), h, ts, f"ETF inflows strong, BTC {d} from here, number {n}", ts + 600, ts + 900,
                          10 + n, 1000 * n, f"https://x.com/{h}/status/{n}"))
        self.con.execute("INSERT INTO calls (id, asset, handle, ts, avail_ts, direction, conditional, confidence, promo, "
                         "unclear, withdraws, horizon_days) VALUES (?,?,?,?,?,?,0,'medium',0,0,0,?)",
                         (str(n), asset, h, ts, ts + 600, d, hz))

    @staticmethod
    def llm(model, instr, text, schema, name, max_output_tokens=0, effort=None):
        ids = [json.loads(ln)["id"] for ln in text.splitlines() if ln.startswith("{")]
        tp = [{"title_en": "ETF flows", "title_hr": "ETF tokovi", "summary_en": "Accounts see strong ETF inflows "
               "pushing BTC to $100k, see https://t.co/x", "summary_hr": "Računi vide jake ETF priljeve.", "ids": ids[:6]},
              {"title_en": "Bogus", "title_hr": "Lažno", "summary_en": "x", "summary_hr": "x", "ids": ["nope", "404"]},
              {"title_en": "One post", "title_hr": "Jedna", "summary_en": "x", "summary_hr": "x", "ids": ids[6:7]}]
        tp += [{"title_en": f"T{k}", "title_hr": f"T{k}", "summary_en": "s", "summary_hr": "s",
                "ids": ids[7 + 2 * k:9 + 2 * k]} for k in range(6)]
        return {"data": {"topics": tp}, "usage": {"in": 10, "out": 5}, "model": model, "cost_usd": 0.001}

    def clean(self, html, what):
        for bad in FORBIDDEN:
            self.assertNotIn(bad.lower(), html.lower(), f"{what}: {bad}")
        self.assertIsNone(ADDRESS.search(html), what)

    def test_mood_flips_and_assets(self):
        m = mood.load(self.con)
        b = m["okviri"]["24h"]
        self.assertEqual(b["broj"], {"bik": 7, "medvjed": 4, "neutralno": 1})
        self.assertEqual(b["presuda"], "blago_bik")                                  # 7 / 11 = 64 %
        self.assertEqual(m["aktivnih"]["24h"], 12)
        self.assertEqual(len(b["racuni"]["bik"][0]["ids"]), 1)
        fl = {f["h"]: (f["prije"], f["sada"]) for f in m["promjene"]}
        self.assertEqual(fl, {"acct1": ("down", "up")})                             # a week ago down, now up
        self.assertIn("ETH", {a for a, x in m["po_imovini"].items() if x["n"]})
        late = mood.load(self.con, public=True)
        self.assertEqual(late["t"], m["ts"] - 7 * D)
        self.assertEqual(late["okviri"]["24h"]["n"], 12)                             # the posts 7 d 6 h old
        self.assertTrue(all(int(i) in self.public_ids for k in mood.SIDES for r in late["okviri"]["24h"]["racuni"][k]
                            for i in r["ids"]))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM mood_d").fetchone()[0], 2)

    def test_topics_validated_capped_and_inside_the_daily_cap(self):
        tp = teme.load(self.con)
        self.assertLessEqual(len(tp["topics"]), 5)
        self.assertNotIn("Lažno", [x["title_hr"] for x in tp["topics"]])          # unknown ids
        self.assertNotIn("Jedna", [x["title_hr"] for x in tp["topics"]])          # one post
        etf = [x for x in tp["topics"] if x["title_en"] == "ETF flows"][0]
        self.assertNotIn("$", etf["summary_en"])
        self.assertNotIn("http", etf["summary_en"])
        self.assertEqual(store.spent(self.con, "openai", "dan", what="teme"), 0.001)
        # the day's topic cap: no request once it is used up, the lexicon instead
        n = []
        c = cfg(narr_openai_usd=0.001)
        r = teme.run(self.con, c, self.now + 60, lambda *_: None, call=lambda *a, **k: n.append(1), force=True)
        self.assertEqual(n, [])
        self.assertIn("strop tema", r["cap"])
        self.assertEqual(r["model"], "ključne riječi")
        self.assertTrue(teme.load(self.con)["topics"])
        self.assertIsNone(teme.run(self.con, c, self.now + 120, lambda *_: None, call=self.llm))   # not due yet

    def test_library_filters(self):
        q = lambda **f: library.query(self.con, library.clean(f))    # noqa: E731
        self.assertEqual(q()["total"], 48)                                           # calls only by default
        self.assertEqual(q(vrsta="sve")["total"], 60)
        self.assertEqual(q(racun="acct3")["total"], 4)
        self.assertEqual(q(imovina="ETH")["total"], 4)
        self.assertEqual(q(stav="neutralno")["total"], 4)
        self.assertEqual(q(stav="medvjed", racun="acct0")["total"], 1)
        self.assertEqual(q(horizont="bez")["total"], 48)
        self.assertEqual(q(horizont="7")["total"], 0)
        day = time.strftime("%Y-%m-%d", time.gmtime(self.now - 2 * D))
        self.assertEqual(q(od=day)["total"], 24)
        self.assertEqual(q(q="number 5")["total"], q(q="number 5")["total"])
        self.assertGreaterEqual(q(q="ETF")["total"], 48)
        self.assertEqual(q(racun="x' OR 1=1 --")["total"], 48)                    # an invalid filter is dropped
        r = q(str="2")
        self.assertEqual((r["page"], r["pages"], len(r["rows"])), (1, 1, 48))
        self.assertTrue(all(x["calls"] for x in q()["rows"]))

    def test_app_tab_sources_library_page_no_forbidden_content(self):
        tab = web.tab_html()
        for s in ("Raspoloženje makro influencera", "Iz čega je izvučeno", "Teme dana", "Promjene stava",
                  "Po imovini", "Ponderirano točnošću", "Biblioteka", "55\u00a0/\u00a045 je neizvjesno"):
            self.assertIn(s, tab)
        self.assertIn("<table class='mi-t nocols'>", tab)                # tidy tables, not the app's card switch
        self.assertIn("href='/kol-makro/acct0'", tab)
        self.assertRegex(tab, r"href='https://x\.com/acct\d+/status/\d+'")
        self.assertIn("/kol-makro/biblioteka?od=", tab)
        self.assertIn('<nav class="mi-seg"', tab)
        self.assertNotIn('class="ms-seg"', tab)                       # the /kol tab script drives only its own segment
        self.clean(tab, "tab")
        _t, lib = appviews.library_page({"racun": "acct3", "vrsta": "sve"})
        self.assertIn("Biblioteka objava", lib)
        self.assertIn("gm, coffee and charts", lib)
        self.assertIn("nije izjava o tržištu", lib)
        self.assertIn("<form class=mi-f", lib)
        self.assertIn("aria-current=\"page\">Biblioteka", lib)
        self.clean(lib.replace("gm, coffee and charts", ""), "library")
        _t, prof = web.profile_page("acct3")
        self.assertIn("/kol-makro/biblioteka?racun=acct3", prof)
        self.clean(prof, "app profile")

    def test_public_hub_mood_topics_index_everything(self):
        self.flag(settings.MAKROINF_JAVNO, "live")
        code, raw, _ = self.public.route("/macro-influencers")
        hub = raw.decode()
        self.assertEqual(code, 200)
        main = hub.split("<main", 1)[1].split("</main>", 1)[0]
        for s in ("Market mood of the influencers", "Where this comes from", "Topics of the day", "By asset",
                  "published with a 7-day delay", "55\u00a0/\u00a045 is uncertain"):
            self.assertIn(s, main)
        self.assertIn('"@type": "Dataset"', hub)
        self.assertIn('"@type": "CollectionPage"', hub)
        self.assertIn('hreflang=hr href="https://example.com/hr/makro-influenceri"', hub)
        self.assertNotIn("noindex", hub)
        # the mood's posts on the public page are older than 7 days; topics link accounts, not today's posts
        ids = [int(x) for x in re.findall(r"x\.com/acct\d+/status/(\d+)", main)]
        self.assertTrue(ids)
        self.assertTrue(set(ids) <= self.public_ids, ids)
        self.clean(main, "hub")
        hr = self.public.route("/hr/makro-influenceri")[1].decode()
        self.assertIn("Iz čega je izvučeno", hr)
        self.assertIn("Teme dana", hr)
        sm = self.public.route("/sitemap.xml")[1].decode()
        day = time.strftime("%Y-%m-%d", time.gmtime(self.now))
        for k in range(12):
            self.assertIn(f"/macro-influencer/acct{k}</loc><lastmod>{day}", sm)
            self.assertIn(f"/hr/makro-influencer/acct{k}</loc>", sm)
            page = self.public.route(f"/macro-influencer/acct{k}")[1].decode()
            self.assertNotIn("noindex", page)
            self.assertIn("still collecting evidence", page)
            self.clean(page.split("<main", 1)[1].split("</main>", 1)[0], f"profile {k}")
        self.assertRegex(sm, r"/macro-influencers</loc><lastmod>" + day)
        self.assertEqual(len([u for u in mpub.urls() if u[0].startswith("/macro-influencer/")]), 12)
        self.assertEqual(web.sitemap_count(), 12)


class History(Base):
    def test_backfilled_history_is_checked_once_at_30_days(self):
        self.con.execute("INSERT INTO accounts (handle, status) VALUES ('a', 'aktivan')")
        self.con.execute("INSERT INTO tweets (id, handle, ts, fetched_ts, kw, macro) VALUES ('old', 'a', ?, ?, 1, 1)",
                         (NOW - 200 * D, NOW - D))
        self.con.execute("INSERT INTO tweets (id, handle, ts, fetched_ts, kw, macro) VALUES ('new', 'a', ?, ?, 1, 1)",
                         (NOW - 2 * D, NOW - 2 * D + 600))
        self.con.commit()
        deleted.sync(self.con)
        st = dict(self.con.execute("SELECT id, stage FROM deletions").fetchall())
        self.assertEqual(st, {"old": 2, "new": 0})
        due = {i for i, _h, _s in deleted.due(self.con, NOW)}
        self.assertEqual(due, {"new"})
        self.assertEqual({i for i, _h, _s in deleted.due(self.con, NOW + 30 * D)}, {"old", "new"})


class Wiring2(Base):
    def test_config_caps_and_the_app_route(self):
        c = store.config({})
        self.assertEqual((c["expand_twapi_usd"], c["expand_openai_usd"], c["day_twapi_usd"], c["day_openai_usd"]),
                         (40.0, 15.0, 1.5, 0.5))
        self.assertEqual((c["expand_n"], c["expand_min"], c["months"], c["last_pages"], c["depth_posts"]),
                         (500, 300, 18, 10, 500))
        self.assertLessEqual(c["narr_openai_usd"], c["day_openai_usd"])
        self.assertEqual(c["narr_model"], "gpt-5-mini")
        self.assertIn(("martypartymusic", "Marty Party", "makro", True), racuni.SEED)
        with open(os.path.join(ROOT, "run_ui.py"), encoding="utf-8") as f:
            self.assertIn('if h == "biblioteka":', f.read())
        # the pilot database gets the new columns on the next connect
        self.assertIn("regularity", {r[1] for r in self.con.execute("PRAGMA table_info(accounts)")})


if __name__ == "__main__":
    unittest.main()
