"""15.11. (vlasnik: "Slažem se s prijedlogom koraka za plan makroinfluencera s dopunama kritičara"): makroinf/,
offline (no network: twitterapi.io, OpenAI and CoinGecko are fakes).

  - the locked rules: version + pinned hash; volatility known AT the call time; no look-ahead; conditional calls start
    only when the condition hits; repeated calls = one episode; the thesis register; horizons pre-registered (no
    horizon = both, half weight each, never the better one); same-bar target / invalidation = conservative miss
  - baselines on the same dates; the three scores, Wilson, shrinkage, "nedovoljno dokaza" below 10 episodes
  - deletion states (pending before confirmed, account states, an empty batch is an API error)
  - the cluster cap, clusters only from data before t_end, the walk-forward without leakage (finished outcomes only,
    the prospective availability, the embargo)
  - the caps stop cleanly (twitterapi pilot, OpenAI), the pilot end-to-end, the quality check and the expansion gate
  - the public pages: switch off = 404 and nothing in the sitemap; on = pages without forbidden content
  - the wiring: flags (MI1 NEVER_LIVE, MI2 owner switch), the owner orders (filtered), fokus exception, MCP, card, the
    DEMO input in veliki/makro (never the real account)

    python3 -m unittest tests.test_makroinf_offline
"""
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import twapi  # noqa: E402
from makroinf import (classify, deleted, fetch, index, prices, quality, racuni, report, rules, run, score,  # noqa: E402
                      store, xapi)
from trade import settings  # noqa: E402

D = 86400
NOW = 1_790_000_000 // D * D + 12 * 3600


def series(pts):
    return prices.Series(pts)


def rising(n=200, start=100.0, step=0.01, end=NOW):
    """Daily closes rising step a day (small noise so the volatility is not 0), the last point at `end`'s day."""
    out, p = [], start
    for k in range(n, -1, -1):
        p *= 1 + step + (0.004 if k % 2 else -0.004)
        out.append((end // D * D - k * D, p))
    return out


def truth_of(pts, asset="BTC"):
    return prices.Truth({asset: series(pts), "total": series(pts)}, {})


def call(i, h="a", ts=NOW - 100 * D, direction="up", asset="BTC", **kw):
    c = {"id": str(i), "handle": h, "asset": asset, "ts": ts, "avail_ts": kw.pop("avail_ts", ts + 3600),
         "direction": direction, "horizon_days": None, "conditional": 0, "trigger_level": None, "trigger_dir": None,
         "target": None, "invalidation": None, "confidence": "medium", "prob": None, "promo": 0, "unclear": 0,
         "withdraws": 0}
    c.update(kw)
    return c


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "makroinf.db")
        self.tdb = os.path.join(self.tmp.name, "trade.db")
        for p in (mock.patch.dict(os.environ, {"MAKROINF_DB": self.db}), mock.patch("usage.meter.record"),
                  mock.patch.object(settings, "DB", self.tdb), mock.patch.dict(prices.FETCH, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.tcon = settings.connect(self.tdb)
        self.addCleanup(self.tcon.close)
        settings._FLAG_CACHE.clear()
        self.addCleanup(settings._FLAG_CACHE.clear)
        self.con = store.connect(self.db)
        self.addCleanup(self.con.close)

    def flag(self, name, mode):
        settings.put(self.tcon, f"flag:{name}", {"mode": mode, "since": 1, "who": "Jure"})
        settings._FLAG_CACHE.clear()


# ---------- the locked rules -------------------------------------------------------------------------------------------

class Rules(Base):
    def test_rules_are_locked_and_versioned(self):
        # changing a number in LOCKED / INDEX_LOCKED after seeing results needs a new version AND a new pinned hash here
        self.assertEqual(rules.RULES_VERSION, "pravila-v1 (15.11.2026.)")
        self.assertEqual(rules.RULES_HASH, "92af98265468")
        self.assertEqual(index.INDEX_HASH, "e3c6ffd557f6")
        self.assertEqual(rules.LOCKED["horizons_d"], [7, 30])
        self.assertEqual(rules.LOCKED["min_episodes"], 10)

    def test_volatility_is_known_at_the_call_time(self):
        pts = rising()
        t_call = NOW - 60 * D + 3600
        tr = truth_of(pts)
        known = [p for t, p in pts if t <= t_call][-31:]
        rets = [math.log(b / a) for a, b in zip(known, known[1:])]
        m = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
        self.assertAlmostEqual(tr.vol("BTC", t_call), sd, 12)
        ep = rules.episodes([call(1, ts=t_call, horizon_days=7)], NOW)[0][0]
        o = rules.evaluate(ep, tr, NOW)[0]
        self.assertAlmostEqual(o["thr"], round(0.5 * sd * math.sqrt(7), 6), 6)
        # the future changes (a crash after the call): the threshold stays, only the outcome may change
        crash = [(t, p * (0.5 if t > t_call + 2 * D else 1)) for t, p in pts]
        o2 = rules.evaluate(ep, truth_of(crash), NOW)[0]
        self.assertEqual(o2["thr"], o["thr"])
        self.assertEqual((o["res"], o2["res"]), ("hit", "miss"))

    def test_no_look_ahead_in_the_start_price_and_trend(self):
        pts = rising()
        tr = truth_of(pts)
        t_call = NOW - 50 * D + 5 * 3600
        ep = rules.episodes([call(1, ts=t_call, horizon_days=7)], NOW)[0][0]
        o = rules.evaluate(ep, tr, NOW)[0]
        self.assertGreaterEqual(o["t_start"], t_call)                       # the first point AFTER the call
        self.assertEqual(o["p0"], tr.daily("BTC").first_at(t_call)[1])
        self.assertIsNone(tr.trend("BTC", pts[0][0] + 3 * D))               # 7 days not known yet: no trend

    def test_conditional_starts_only_when_the_condition_hits(self):
        pts = [(NOW // D * D - k * D, 70_000.0 + (k % 3) * 300) for k in range(120, -1, -1)]
        t_call = NOW - 80 * D
        # the condition never hits within 30 days: neaktiviran (not scored)
        ep = rules.episodes([call(1, ts=t_call, conditional=1, trigger_level=60_000, trigger_dir="below",
                                  direction="down", horizon_days=7)], NOW)[0][0]
        self.assertEqual(rules.evaluate(ep, truth_of(pts), NOW)[0]["res"], "neaktiviran")
        # not yet expired: ceka
        ep2 = rules.episodes([call(2, ts=NOW - 10 * D, conditional=1, trigger_level=60_000, trigger_dir="below",
                                   direction="down", horizon_days=7)], NOW)[0][0]
        self.assertEqual(rules.evaluate(ep2, truth_of(pts), NOW)[0]["res"], "ceka")
        # it hits on day +5: the start is that point, p0 the price there
        hit_t = t_call // D * D + 5 * D
        pts2 = [(t, (59_000.0 if t >= hit_t else p) * (0.96 ** max(0, (t - hit_t) // D))) for t, p in pts]
        o = rules.evaluate(ep, truth_of(pts2), NOW)[0]
        self.assertEqual(o["t_start"], hit_t)
        self.assertEqual(o["p0"], 59_000.0)
        self.assertEqual(o["res"], "hit")
        # a conditional call without a level is not measured
        _e, _r, sk = rules.episodes([call(3, conditional=1, trigger_level=None)], NOW)
        self.assertEqual(sk, {"uvjet_bez_razine": 1})

    def test_repeated_calls_are_one_episode_and_the_register(self):
        t = NOW - 200 * D
        cs = [call(1, ts=t), call(2, ts=t + 3 * D), call(3, ts=t + 10 * D),      # same thesis within 14 d: one
              call(4, ts=t + 12 * D, direction="down"),                          # change
              call(5, ts=t + 60 * D, direction="down"),                          # gap > 14 d: expiry + a new one
              call(6, ts=t + 62 * D, withdraws=1),                               # withdrawal
              call(7, ts=t + 63 * D, unclear=1), call(8, ts=t + 64 * D, confidence="joke"),
              call(9, ts=t + 65 * D, promo=1)]
        eps, reg, sk = rules.episodes(cs, NOW)
        self.assertEqual([(e["first_id"], e["n_calls"], e["direction"]) for e in eps],
                         [("1", 3, "up"), ("4", 1, "down"), ("5", 1, "down")])
        self.assertEqual([r["event"] for r in reg], ["aktivacija", "ponavljanje", "ponavljanje", "promjena",
                                                     "aktivacija", "istek", "aktivacija", "povlacenje"])
        self.assertEqual(sk, {"nejasno": 1, "sala": 1, "promocija": 1})

    def test_horizons_are_pre_registered_never_the_better_one(self):
        self.assertEqual([rules.bucket(x) for x in (None, 3, 14, 15, 60, 61)], ["oba", "7", "7", "30", "30", "dugo"])
        # rises 7 days, then falls: a no-horizon "up" call is a hit at 7 d and a miss at 30 d
        base = NOW // D * D - 120 * D
        pts = [(base + k * D, 100 * (1.004 if k % 2 else 0.996)) for k in range(61)]
        p = pts[-1][1]
        for k in range(1, 8):
            p *= 1.05
            pts.append((base + (60 + k) * D, p))
        for k in range(8, 40):
            p *= 0.97
            pts.append((base + (60 + k) * D, p))
        t_call = base + 60 * D + 60
        ep = rules.episodes([call(1, ts=t_call)], NOW)[0][0]
        outs = rules.evaluate(ep, truth_of(pts), NOW)
        self.assertEqual([(o["horizon"], o["w"], o["res"]) for o in outs], [("7", 0.5, "hit"), ("30", 0.5, "miss")])
        p_ = score.predictive(outs)
        self.assertEqual((p_["pogoci_tezinski"], p_["n_tezinski"], p_["pogodak"]), (0.5, 1.0, 0.5))
        hz = score.by_horizon(outs)   # both shown, separately
        self.assertEqual((hz["bez_roka_7d"]["pogodak"], hz["bez_roka_30d"]["pogodak"]), (1.0, 0.0))
        e7 = rules.episodes([call(2, ts=t_call, horizon_days=10)], NOW)[0][0]
        self.assertEqual([o["horizon"] for o in rules.evaluate(e7, truth_of(pts), NOW)], ["7"])
        e_long = rules.episodes([call(3, ts=t_call, horizon_days=365)], NOW)[0][0]
        self.assertEqual(rules.evaluate(e_long, truth_of(pts), NOW)[0]["res"], "dugo")

    def test_target_and_invalidation_in_one_bar_is_a_miss(self):
        self.assertEqual(rules.level_test([(1, 95, 111)], 100, 110, 96), "invalidacija")   # both inside one bar
        self.assertEqual(rules.level_test([(1, 99, 105), (2, 104, 112)], 100, 110, 96), "cilj")
        self.assertEqual(rules.level_test([(1, 95, 101), (2, 104, 112)], 100, 110, 96), "invalidacija")
        self.assertEqual(rules.level_test([(1, 99, 101)], 100, 110, 96), "nije")

    def test_turn_and_range_tests(self):
        s = 0.1
        self.assertEqual(rules.direction_test("bottom_in", 100, 112, [99, 104, 112], s), "hit")
        self.assertEqual(rules.direction_test("bottom_in", 100, 120, [94, 120], s), "miss")      # a lower low
        self.assertEqual(rules.direction_test("bottom_in", 100, 103, [99, 103], s), "flat")
        self.assertEqual(rules.direction_test("top_in", 100, 88, [101, 88], s), "hit")
        self.assertEqual(rules.direction_test("range", 100, 101, [98, 102, 101], s), "hit")
        self.assertEqual(rules.direction_test("range", 100, 101, [85, 101], s), "miss")


class Baselines(Base):
    def test_baselines_on_the_same_dates(self):
        pts = rising()
        tr = truth_of(pts)
        t_call = NOW - 60 * D
        up = rules.evaluate(rules.episodes([call(1, ts=t_call, horizon_days=7)], NOW)[0][0], tr, NOW)[0]
        dn = rules.evaluate(rules.episodes([call(2, ts=t_call, horizon_days=7, direction="down")], NOW)[0][0], tr,
                            NOW)[0]
        for o in (up, dn):   # the same asset, start, horizon, threshold for both calls
            self.assertEqual((o["b_bull"], o["b_rand_hit"], o["b_rand_dec"], o["b_trend"]), ("hit", 0.5, 1.0, "hit"))
            self.assertEqual(o["t_start"], up["t_start"])
        self.assertEqual((up["res"], dn["res"]), ("hit", "miss"))
        self.assertAlmostEqual(up["follow"], up["ret"] - rules.LOCKED["cost"]["BTC"], 6)
        self.assertAlmostEqual(dn["follow"], -dn["ret"] - rules.LOCKED["cost"]["BTC"], 6)
        p = score.predictive([dn])
        self.assertEqual(p["bazne"], {"uvijek_bik": 1.0, "nasumicno": 0.5, "trend_7d": 1.0})


# ---------- scores ------------------------------------------------------------------------------------------------------

def outs(n_hit, n_miss, h="a"):
    xs = []
    for i in range(n_hit + n_miss):
        xs.append({"eid": f"{h}:{i}", "first_id": str(i), "handle": h, "horizon": "7", "hz": "7", "w": 1.0,
                   "res": "hit" if i < n_hit else "miss", "b_bull": "hit", "b_rand_hit": 0.5, "b_rand_dec": 1.0,
                   "b_trend": "miss", "follow": 0.02 if i < n_hit else -0.02, "b_bull_follow": 0.01, "prob": None,
                   "done_ts": NOW - D})
    return xs


class Scores(Base):
    def test_wilson_and_insufficient_evidence(self):
        lo, hi = score.wilson(8, 10)
        self.assertAlmostEqual(lo, 0.4902, 3)                 # the critic's example: 8/10 -> ~49 %
        self.assertAlmostEqual(hi, 0.9433, 3)
        self.assertEqual(score.wilson(0, 0), (None, None))
        self.assertEqual(score.predictive(outs(8, 1))["presuda"], score.VERDICT_FEW)   # 9 episodes
        p = score.predictive(outs(9, 1))
        self.assertNotEqual(p["presuda"], score.VERDICT_FEW)
        self.assertLess(score.predictive(outs(9, 1), prior=0.5)["skupljeno"], 0.9)     # shrunk toward the prior

    def test_three_separate_scores_never_a_product(self):
        s = score.account(outs(12, 3), 20, {"1": "confirmed_deleted", "2": "exists", "3": "account_suspended"}, 2)
        self.assertEqual(set(s), {"prediktivno", "ekonomski", "integritet", "po_horizontu", "stanja"})
        self.assertEqual(s["integritet"]["naknadno_nedostupno"], 2)
        self.assertEqual(s["integritet"]["kazna"], "nema (dok dokaz nije jak)")
        self.assertAlmostEqual(s["ekonomski"]["razlika"], (12 * 0.02 - 3 * 0.02) / 15 - 0.01, 4)
        self.assertIn("premalo", s["integritet"]["promasaji_prema_pogocima"])          # < 10 misses: no comparison
        self.assertEqual(score.rank({"a": s, "b": score.account(outs(2, 1, "b"), 3, {}, 0)}), ["a", "b"])

    def test_brier_only_with_an_explicit_probability(self):
        xs = outs(3, 1)
        self.assertIsNone(score.predictive(xs)["brier"])
        xs[0]["prob"], xs[3]["prob"] = 0.8, 0.6
        self.assertAlmostEqual(score.predictive(xs)["brier"], ((0.8 - 1) ** 2 + (0.6 - 0) ** 2) / 2, 4)


# ---------- deletions -------------------------------------------------------------------------------------------------

class FakeX:
    """twitterapi.io: user info, advanced search (20 posts a page inside the query's window), user search, posts by
    id (minus the deleted ones), followings."""

    def __init__(self, deleted=(), suspended=(), small=(), per_page=20):
        self.deleted, self.suspended, self.small, self.per_page = set(deleted), set(suspended), set(small), per_page
        self.calls = []

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        if url == twapi.USER_URL:
            h = params["userName"]
            if h in self.suspended:
                return {"status": "error", "msg": "User is suspended"}
            return {"status": "success", "data": {"userName": h, "name": h.title(), "id": "9",
                                                  "followers": 5_000 if h in self.small else 250_000,
                                                  "statusesCount": 12_000, "createdAt": "2019-01-01"}}
        if url == twapi.URL:
            q = params["query"]
            h = re.search(r"from:(\w+)", q).group(1)
            a = int(re.search(r"since_time:(\d+)", q).group(1)) if "since_time" in q else NOW - 30 * D
            b = int(re.search(r"until_time:(\d+)", q).group(1)) if "until_time" in q else NOW
            page = int(params.get("cursor") or 0)
            tws = []
            for k in range(self.per_page):
                ts = b - 3600 * (1 + k + page * self.per_page)
                if ts <= a:
                    break
                tid = str(abs(hash((h, ts))) % 10 ** 15)
                tws.append({"id": tid, "createdAt": ts, "text": f"BTC will go {'up' if k % 2 else 'down'} from here, "
                                                                f"bullish cycle", "lang": "en", "likeCount": 5,
                            "author": {"userName": h}, "url": f"https://x.com/{h}/status/{tid}"})
            return {"tweets": tws, "has_next_page": len(tws) == self.per_page, "next_cursor": str(page + 1)}
        if url == xapi.USER_SEARCH_URL:
            return {"users": [{"userName": "NekiTrades", "name": "Neki", "followers": 180_000,
                               "description": "crypto trader, BTC charts"},
                              {"userName": "neki_cats", "name": "Neki", "followers": 300, "description": "cats"}]}
        if url == twapi.TWEETS_URL:
            ids = params["tweet_ids"].split(",")
            return {"tweets": [{"id": i} for i in ids if i not in self.deleted]}
        if url == twapi.FOLLOWINGS_URL:
            return {"followings": [{"userName": f"big{k}", "followers": 500_000, "description": "macro analyst"}
                                   for k in range(3)]}
        raise AssertionError(url)


class Deletions(Base):
    def setUp(self):
        super().setUp()
        for h in ("a", "susp"):
            self.con.execute("INSERT INTO accounts (handle, status) VALUES (?, 'aktivan')", (h,))
        for i in ("1", "2", "3", "4", "5"):
            self.con.execute("INSERT INTO tweets (id, handle, ts, fetched_ts, kw, macro) VALUES (?,?,?,?,1,1)",
                             (i, "susp" if i == "5" else "a", NOW - 40 * D, NOW - 3 * D))
        self.con.commit()
        self.c = {**store.config(), "pilot_twapi_usd": 1.0}

    def test_pending_then_confirmed_account_states(self):
        fx = FakeX(deleted={"2", "5"}, suspended={"susp"})
        r = deleted.check(self.con, self.c, NOW, fx)
        st = deleted.states(self.con)
        self.assertEqual((st["1"], st["2"], st["5"]), ("exists", "pending", "account_suspended"))
        self.assertEqual(r["pending"], 1)
        self.assertEqual(deleted.check(self.con, self.c, NOW + 3600, fx)["checked"], 0)   # the recheck waits 6 h
        deleted.check(self.con, self.c, NOW + 7 * 3600, fx)
        self.assertEqual(deleted.states(self.con)["2"], "confirmed_deleted")              # missing twice
        self.assertEqual(self.con.execute("SELECT stage FROM deletions WHERE id='1'").fetchone()[0], 1)

    def test_an_empty_batch_is_an_api_error_never_all_deleted(self):
        fx = FakeX(deleted={"1", "2", "3", "4", "5"})
        deleted.check(self.con, self.c, NOW, fx)
        self.assertEqual(set(deleted.states(self.con).values()), {"api_error"})


# ---------- the index -------------------------------------------------------------------------------------------------

class Index(Base):
    def test_cluster_cap(self):
        st = {"a": 1, "b": 1, "c": 1, "d": -1}
        cl = {"a": "a", "b": "a", "c": "a", "d": "d"}
        v, n, ncl = index.value(st, {h: 1.0 for h in st}, cl)
        self.assertAlmostEqual(v, (1.5 - 1) / 2.5, 6)   # the cluster of 3 counts as 1.5, not 3
        self.assertEqual((n, ncl), (4, 2))
        self.assertAlmostEqual(index.value(st, {h: 1.0 for h in st}, {})[0], 0.5, 6)
        self.assertEqual(index.value({"x": 1}, {}, {}), (None, 0, 0))   # no weight -> no vote (not neutral)

    def test_clusters_only_from_data_before_t_end(self):
        quotes = [("a", "b", NOW - 10 * D + k) for k in range(6)]
        cl = index.clusters([], {"a": [], "b": [], "c": []}, quotes, NOW)
        self.assertEqual(cl["a"], cl["b"])
        self.assertNotEqual(cl["a"], cl["c"])
        cl2 = index.clusters([], {"a": [], "b": []}, quotes, NOW - 20 * D)   # the quotes come later: no cluster
        self.assertNotEqual(cl2["a"], cl2["b"])

    def test_stance_availability_and_inactivity(self):
        cs = [call(1, ts=NOW - 5 * D, avail_ts=NOW - D)]
        self.assertIsNone(index.stance(cs, NOW - 3 * D, "prospektivno", {}))   # fetched later: not known yet
        self.assertEqual(index.stance(cs, NOW - 3 * D, "povijesno", {})[0], 1)
        self.assertEqual(index.stance(cs, NOW, "prospektivno", {})[0], 1)
        self.assertIsNone(index.stance(cs, NOW + 40 * D, "prospektivno", {}))  # expired: no vote, not "neutral"
        cs.append(call(2, ts=NOW - D, avail_ts=NOW - D + 60, withdraws=1))
        self.assertIsNone(index.stance(cs, NOW, "prospektivno", {}))
        cond = [call(3, ts=NOW - 5 * D, conditional=1, trigger_level=1, trigger_dir="below", direction="down")]
        self.assertIsNone(index.stance(cond, NOW, "povijesno", {}))              # not activated
        self.assertEqual(index.stance(cond, NOW, "povijesno", {"3": NOW - D})[0], -1)

    def test_walk_forward_no_leakage(self):
        o = outs(5, 0, "a") + outs(0, 5, "b")
        for x in o[:5]:
            x["done_ts"] = NOW + 5 * D       # a's hits finish in the future
        acc = index.accuracy_at(o, NOW)
        self.assertNotIn("a", acc)            # unfinished outcomes do not exist yet
        self.assertIn("b", acc)
        days = list(range(NOW // D * D - 100 * D, NOW // D * D, D))
        tr, va, te = index.splits(days)
        self.assertLess(tr[-1], va[0] - index.INDEX_LOCKED["embargo_d"] * D + 1)
        self.assertLess(va[-1], te[0] - index.INDEX_LOCKED["embargo_d"] * D + 1)
        self.assertEqual(te, days[75:])
        # a day's index does not change when calls fetched / outcomes finished after it are added
        pts = rising(300)
        trh = truth_of(pts)
        cs = [call(i, h=f"h{i % 6}", ts=NOW - (200 - i) * D, direction="up" if i % 3 else "down") for i in range(150)]
        d0 = NOW // D * D - 60 * D
        s1 = index.series(cs, o, trh, [d0], k=5)
        later = cs + [call(900 + i, h=f"h{i}", ts=d0 + D + i * 3600, direction="down") for i in range(6)]
        later_o = o + [dict(x, done_ts=d0 + 2 * D, handle="h1") for x in outs(9, 0, "h1")]
        self.assertEqual(index.series(later, later_o, trh, [d0], k=5), s1)

    def test_overlay_and_demo_check(self):
        dani = {NOW // D * D: {"top": -0.6, "n_top": 4}, NOW // D * D - D: {"top": -0.6, "n_top": 1}}
        ov = index.overlay_days(dani, 0.5, {NOW // D: "neutral", NOW // D - 1: "risk_on"})
        self.assertEqual(ov, {NOW // D: "risk_off", NOW // D - 1: "risk_on"})   # too few accounts: no change
        self.assertFalse(index.demo_check(NOW)[0])                              # no state yet: nothing blocks
        store.kv(self.con, "ulaz", {"state": "aktivan"})
        store.kv(self.con, "walk", {"thr": 0.5})
        self.con.execute("INSERT INTO index_d VALUES (?,?,?,?,?,?,?)", (NOW // D * D, "BTC", "prospektivno", "top",
                                                                         -0.7, 5, None))
        self.con.commit()
        b, why, v = index.demo_check(NOW)
        self.assertTrue(b)
        self.assertIn("−0.5", why.replace("-", "−"))

    def test_input_state_degrades(self):
        store.kv(self.con, "provjera", {"passed": True})
        self.con.execute("INSERT INTO index_d VALUES (?,?,?,?,?,?,?)", (NOW // D * D, "BTC", "prospektivno", "top",
                                                                         0.2, 5, None))
        ok = {"validacija": {"n": 30, "pogodak": 0.6, "uvijek_bik": 0.5}}
        self.assertEqual(index.input_state(self.con, ok, {}, NOW)["state"], "aktivan")
        bad = {"validacija": {"n": 30, "pogodak": 0.4, "uvijek_bik": 0.5}}
        self.assertEqual(index.input_state(self.con, bad, {}, NOW)["state"], "iskljucen")
        ev = {"razlika_pp": -1.0, "s_indeksom": {"n": 40}}
        self.assertEqual(index.input_state(self.con, ok, ev, NOW)["state"], "iskljucen")
        store.kv(self.con, "provjera", {"passed": False})
        self.assertEqual(index.input_state(self.con, ok, {}, NOW)["state"], "na_cekanju")


# ---------- budgets, the pilot end-to-end, quality, expansion ------------------------------------------------------

def fake_llm(macro_share=2):
    """OpenAI fake: every macro_share-th post is a BTC call (up / down by its text), the rest not macro."""
    def call(model, instr, text, schema, name, max_output_tokens=0, effort=None):
        items = [json.loads(ln) for ln in text.splitlines() if ln.startswith("{")]
        calls, nm = [], []
        for k, x in enumerate(items):
            if k % macro_share == 0:
                calls.append({"id": x["id"], "asset": "BTC", "direction": "up" if "up" in x["text"] else "down",
                              "horizon_days": None, "conditional": False, "condition": None, "trigger_level": None,
                              "trigger_dir": "none", "target": None, "invalidation": None, "confidence": "medium",
                              "probability": None, "promo": False, "unclear": False, "withdraws": False})
            else:
                nm.append(x["id"])
        if name == "provjera_oznaka":
            data = {"items": [{"id": x["id"], "is_macro": x["proposed"]["is_macro"],
                               "asset": "BTC" if x["proposed"]["is_macro"] else "none",
                               "direction": (x["proposed"]["calls"] or [{"direction": "none"}])[0]["direction"],
                               "proposed_ok": True} for x in items]}
        else:
            data = {"calls": calls, "not_macro": nm}
        return {"data": data, "usage": {"in": 100, "out": 50}, "model": model, "cost_usd": 0.002}
    return call


class Budget(Base):
    def test_twitterapi_pilot_cap_stops_cleanly(self):
        c = {**store.config(), "pilot_twapi_usd": 0.0075}   # 2 pages of 20 posts (0.003 each) + a bit
        racuni.seed(self.con, NOW, path=os.path.join(self.tmp.name, "none.json"))
        self.con.execute("UPDATE accounts SET status = 'aktivan' WHERE handle NOT LIKE '?%'")
        r = fetch.backfill(self.con, c, NOW, FakeX())
        self.assertIn("strop twitterapi (pilot)", r["cap"])
        self.assertLessEqual(store.spent(self.con, "twitterapi", "pilot"), 0.0075 + 1e-9)
        self.assertAlmostEqual(store.spent(self.con, "twitterapi", "pilot"), 0.006, 9)

    def test_openai_cap_stops_before_a_request_that_could_cross_it(self):
        for k in range(60):
            self.con.execute("INSERT INTO accounts (handle, status, category) VALUES (?, 'aktivan', 'ta')", (f"h{k % 3}",)) \
                if k < 3 else None
            self.con.execute("INSERT INTO tweets (id, handle, ts, text, fetched_ts, kw) VALUES (?,?,?,?,?,1)",
                             (str(k), f"h{k % 3}", NOW - k * D, "btc up bullish", NOW))
        self.con.commit()
        c = {**store.config(), "pilot_openai_usd": 0.012}   # one request fits, the next one's maximum does not
        n = []
        llm = fake_llm()

        def counting(*a, **k):
            n.append(1)
            return llm(*a, **k)
        r = classify.run(self.con, c, NOW, call=counting)
        self.assertIn("strop OpenAI (pilot)", r["cap"])
        self.assertLessEqual(store.spent(self.con, "openai", "pilot"), 0.02)
        self.assertEqual(len(n), 1)
        row = self.con.execute("SELECT cls_v, cls_model FROM tweets WHERE cls_ts IS NOT NULL AND cls_v <> 'predfiltar' "
                               "LIMIT 1").fetchone()
        self.assertEqual(row, (classify.PROMPT_VERSION, "gpt-5-mini"))   # the audit trail
        self.assertEqual(self.con.execute("SELECT DISTINCT prompt_v FROM calls").fetchall(),
                         [(classify.PROMPT_VERSION,)])


class Pilot(Base):
    def setUp(self):
        super().setUp()
        own = os.path.join(self.tmp.name, "vlasnik.json")
        with open(own, "w") as f:
            json.dump({"dodaj": [{"name": "Neki", "handle": None}], "makni": ["tier10k"], "potvrdi": {}}, f)
        self.own = own
        prices.FETCH["chart"] = lambda coin, days: {"prices": [[t * 1000, p] for t, p in rising(
            400 if days > 90 else 90, 30_000 if coin == "bitcoin" else 10)]}

    def test_pilot_end_to_end(self):
        fx = FakeX(small={"PeterSchiff"}, suspended={"glassnode"})
        lines = []
        c = {**store.config(), "months": 2, "last_pages": 1}
        with mock.patch.object(racuni, "OWNER_FILE", self.own), mock.patch.object(store, "config", lambda cfg=None: c):
            for _ in range(6):
                run.krug(NOW, lines.append, get=fx, call=fake_llm(), budget_s=600, refresh_prices=True)
        st = dict(self.con.execute("SELECT handle, status FROM accounts").fetchall())
        self.assertEqual(st["honey_xbt"], "aktivan")                             # Hani: the owner's confirmed handle
        self.assertNotIn("?Hani", st)
        self.assertEqual(self.con.execute("SELECT owner_seed, source FROM accounts WHERE handle = 'honey_xbt'").fetchone(),
                         (1, "vlasnik"))
        self.assertEqual(st["?Neki"], "needs_owner_confirm")                     # a name without a handle: never guessed
        self.assertEqual(st["tier10k"], "uklonjen")                              # the owner's removal
        self.assertEqual(st["PeterSchiff"], "odbijen")                           # under 100k
        self.assertEqual(st["glassnode"], "odbijen")                             # unavailable
        self.assertEqual(st["100trillionUSD"], "aktivan")
        cand = racuni.candidates(self.con)
        self.assertEqual([x["handle"] for x in cand if x["for_name"] == "Neki"], ["NekiTrades"])
        self.assertEqual([x for x in cand if x["for_name"] == "Hani"], [])     # no candidates for Hani
        self.assertTrue(store.kv(self.con, "pilot_twapi_done"))
        self.assertTrue(store.kv(self.con, "pilot_openai_done"))
        self.assertTrue(store.kv(self.con, "prvi_izracun"))
        self.assertTrue(any(ln.startswith("makroinf: sat: ") for ln in lines))
        self.assertGreater(self.con.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 0)
        self.assertTrue((store.kv_json(self.con, "provjera") or {}).get("ts"))   # the quality check ran once
        self.assertLessEqual(store.spent(self.con, "twitterapi", "pilot"), c["pilot_twapi_usd"])
        # no retweets in the query, monthly windows spread over the months
        qs = [p["query"] for u, p in fx.calls if u == twapi.URL]
        self.assertTrue(all("-filter:retweets" in q for q in qs))
        self.assertGreaterEqual(len({re.search(r"until_time:(\d+)", q).group(1) for q in qs if "until_time" in q}), 4)
        d = report.data()
        self.assertTrue(report.rank_rows(d))
        self.assertIn("makroinf: sat:", report.hour_line(self.con, NOW))
        # the owner confirms a candidate: the placeholder goes, the others are rejected, the account is measured
        with open(self.own, "w") as f:
            json.dump({"dodaj": [{"name": "Neki", "handle": None}], "potvrdi": {"Neki": "NekiTrades"}}, f)
        racuni.seed(self.con, NOW, self.own)
        st = dict(self.con.execute("SELECT handle, status FROM accounts").fetchall())
        self.assertNotIn("?Neki", st)
        self.assertEqual(st["NekiTrades"], "novo")
        self.assertEqual({x["handle"]: x["status"] for x in racuni.candidates(self.con) if x["for_name"] == "Neki"},
                         {"NekiTrades": "potvrden"})


class Quality(Base):
    def test_metrics_per_category_and_the_expansion_gate(self):
        rows = [{"category": "ta", "ours_macro": True, "ours_dir": "up", "critic_macro": True, "critic_dir": "up"}] * 12
        rows += [{"category": "makro", "ours_macro": True, "ours_dir": "up", "critic_macro": k > 3,
                  "critic_dir": "up"} for k in range(12)]
        rows += [{"category": "vijesti", "ours_macro": False, "ours_dir": "none", "critic_macro": False,
                  "critic_dir": "none"}] * 12
        by, passed, why = quality.metrics(rows)
        self.assertFalse(passed)
        self.assertEqual(by["makro"]["precision"], round(8 / 12, 3))
        self.assertIn("makro", why)
        for h in ("a1", "a2", "a3"):
            self.con.execute("INSERT INTO accounts (handle, status, source, category) VALUES (?, 'aktivan', 'sjeme', "
                             "'ta')", (h,))
        ok, txt = run.expand(self.con, get=FakeX())
        self.assertFalse(ok)
        self.assertIn("odbijeno", txt)
        ok, txt = run.expand(self.con, force=True, who="Jure", get=FakeX(), target=5)
        self.assertTrue(ok, txt)
        self.assertTrue(store.kv_json(self.con, "provjera")["forced"])
        self.assertEqual(self.con.execute("SELECT handle, source, status FROM accounts WHERE source = 'prosirenje' "
                                          "ORDER BY handle").fetchall(), [("big0", "prosirenje", "novo"),
                                                                          ("big1", "prosirenje", "novo")])

    def test_stratified_sample(self):
        pop = [{"id": str(i), "category": ["ta", "makro"][i % 2], "stratum": f"{['ta', 'makro'][i % 2]}/"
                f"{'ne_makro' if i % 5 else 'gore'}", "macro": not i % 5, "calls": [], "text": "", "handle": "a",
                "url": "", "ts": NOW} for i in range(1000)]
        smp = quality.sample(pop)
        self.assertEqual(len(smp), 300)
        self.assertEqual(len({x["stratum"] for x in smp}), 4)
        self.assertEqual(quality.sample(pop), smp)                    # deterministic
        sub = quality.critic_subset(smp)
        self.assertEqual(len(sub), 100)
        self.assertEqual(sum(1 for x in sub if x["category"] == "ta"), 50)


# ---------- public pages --------------------------------------------------------------------------------------------

FORBIDDEN = ("twitterapi", "openai", "gpt-", "api key", "_KEY", "TWITTERAPI", "makroinf.db", "render", "coingecko",
             "trošak", "cost", " $", "wallet", "novčanik", "skriva")


class Public(Base):
    def setUp(self):
        super().setUp()
        from ui import public
        self.public = public
        public._cache.clear()
        self.addCleanup(public._cache.clear)
        p = mock.patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://example.com",
                                         "KOL_DB": os.path.join(self.tmp.name, "kol.db")})
        p.start()
        self.addCleanup(p.stop)
        pts = rising(330, 30_000)
        self.con.executemany("INSERT INTO px VALUES (?,?,?,?)", [("bitcoin", "d", t, p) for t, p in pts])
        self.con.execute("INSERT INTO accounts (handle, name, category, status) VALUES ('MacroMan', 'Macro Man', 'makro', "
                         "'aktivan')")
        for k in range(14):   # 15 days apart: every call is its own episode
            ts = NOW - (260 - 15 * k) * D
            self.con.execute("INSERT INTO tweets (id, handle, ts, text, fetched_ts, kw, macro) VALUES (?,?,?,?,?,1,1)",
                             (str(100 + k), "MacroMan", ts, "SECRET-TEXT btc up", NOW - 2 * D))
            self.con.execute("INSERT INTO calls (id, asset, handle, ts, avail_ts, direction, conditional, confidence, "
                             "promo, unclear, withdraws) VALUES (?, 'BTC', 'MacroMan', ?, ?, ?, 0, 'medium', 0, 0, 0)",
                             (str(100 + k), ts, NOW - 2 * D, "up" if k % 4 else "down"))
        self.con.execute("INSERT INTO deletions (id, handle, base_ts, stage, state) VALUES ('100', 'MacroMan', 1, 1, "
                         "'confirmed_deleted')")
        self.con.commit()
        run.score_all(self.con, NOW)

    def test_switch_off_404_and_not_in_the_sitemap(self):
        for path in ("/macro-influencers", "/hr/makro-influenceri", "/macro-influencer/MacroMan",
                     "/hr/makro-influencer/MacroMan"):
            self.assertEqual(self.public.route(path)[0], 404, path)
        sm = self.public.route("/sitemap.xml")[1].decode()
        self.assertNotIn("macro-influencer", sm)
        self.assertNotIn("macro-influencer", self.public.robots())

    def test_switch_on_pages_without_forbidden_content(self):
        self.flag(settings.MAKROINF_JAVNO, "live")
        code, raw, _ = self.public.route("/macro-influencers")
        html = raw.decode()
        self.assertEqual(code, 200)
        self.assertIn("/macro-influencer/MacroMan", html)
        self.assertIn('hreflang=hr href="https://example.com/hr/makro-influenceri"', html)
        code, raw, _ = self.public.route("/macro-influencer/MacroMan")
        page = raw.decode()
        self.assertEqual(code, 200)
        self.assertIn("later unavailable", page)                          # the deleted post: no link
        self.assertNotIn("/status/100\"", page)
        self.assertIn("/status/113", page)                                # the others link to the original
        self.assertNotIn("SECRET-TEXT", page + html)                     # no post text copied
        code, raw, _ = self.public.route("/hr/makro-influencer/MacroMan")
        hr = raw.decode()
        self.assertIn("naknadno nedostupno", hr)
        for txt in (html, page, hr):
            body = txt.split("<main", 1)[1].split("</main>", 1)[0]
            for bad in FORBIDDEN:
                self.assertNotIn(bad.lower(), body.lower(), bad)
        self.assertIn("/macro-influencer/MacroMan", self.public.sitemap())
        self.assertIn("Allow: /macro-influencer", self.public.robots())
        self.assertEqual(self.public.route("/macro-influencer/nobody")[0], 404)
        self.assertIsNone(self.public.route("/hr/macro-influencer/MacroMan"))          # no mixed-language paths

    def test_small_n_is_noindex(self):
        self.flag(settings.MAKROINF_JAVNO, "live")
        self.con.execute("DELETE FROM calls WHERE CAST(id AS INTEGER) > 104")
        self.con.commit()
        run.score_all(self.con, NOW)
        page = self.public.route("/macro-influencer/MacroMan")[1].decode()
        self.assertIn('noindex', page)
        self.assertIn("insufficient evidence", page)
        self.assertNotIn("/macro-influencer/MacroMan", self.public.sitemap())


# ---------- wiring ----------------------------------------------------------------------------------------------------

class Wiring(Base):
    def test_flags_and_the_owner_orders(self):
        from ui import assistnotes
        self.assertEqual(settings.FLAGS[settings.MAKROINF][0], "MI1")
        self.assertEqual(settings.FLAGS[settings.MAKROINF_JAVNO][0], "MI2")
        self.assertIn(settings.MAKROINF, settings.NEVER_LIVE)
        self.assertIn(settings.MAKROINF, settings.PROFILE_FLAGS)
        self.assertNotIn(settings.MAKROINF, settings.OWNER_SWITCHES)
        self.assertIn(settings.MAKROINF_JAVNO, settings.OWNER_SWITCHES)
        self.assertIn(settings.MAKROINF_JAVNO, settings.OWNER_SWITCH_NOTES)
        codes = [v[0] for v in settings.FLAGS.values()]
        self.assertEqual((codes.count("MI1"), codes.count("MI2")), (1, 1))   # no clash of plan codes
        # 15.11.: the index order, then the owner's order to publish (makroinf_javno live; tests/test_makrojavno_offline):
        # filtered by name, never pinned to a position (later orders are appended after them)
        mine = tuple(o for o in assistnotes.OWNER_FLAG_ORDERS if o[0] == settings.MAKROINF)
        self.assertEqual([o[:2] for o in mine], [(settings.MAKROINF, "paper")])
        self.assertEqual([o[:2] for o in assistnotes.OWNER_FLAG_ORDERS if o[0] == settings.MAKROINF_JAVNO],
                         [(settings.MAKROINF_JAVNO, "live")])
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", mine):
            self.assertEqual(assistnotes.owner_flag_orders(self.tcon), ["zastavica makroinf_indeks: off → paper"])
        with self.assertRaises(ValueError):
            settings.set_flag(self.tcon, settings.MAKROINF, "live", "Jure")              # NEVER_LIVE
        with self.assertRaises(ValueError):
            settings.set_flag(self.tcon, settings.MAKROINF_JAVNO, "live", "neko_drugi")  # only the owner publishes

    def test_fokus_exception_cpuguard_start_sh(self):
        from ops import cpuguard, fokus
        with mock.patch.dict(os.environ, {"FOKUS_MIDCAP_FORCE": "1"}):
            self.assertIsNone(fokus.skip_cmd(["python3", "run_makroinf.py", "krug"]))
            self.assertIn("makroinf", fokus.start_line())
        self.assertEqual(cpuguard.classify(["python3", "run_makroinf.py", "krug"])[0], "makroinf")
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn("low python3 run_makroinf.py krug", sh)
        self.assertIn("ops.heavy --night run_makroinf.py noc", sh)

    def test_mcp_card_critic_morning(self):
        from critic import deep
        from ui import mcpapi
        self.assertIn("get_macro_influencers", [t["name"] for t in mcpapi.TOOLS])
        self.assertIn("makro_influenceri", [k for k, _f in deep.CONTEXT_BLOCKS])
        d, err = mcpapi._tool("get_macro_influencers", {"limit": 3})
        self.assertFalse(err)
        self.assertFalse(d["available"])           # no accounts yet: the pilot has not started
        self.assertIn("pilot", d["note"])
        self.assertEqual(report.card_html(lambda *a, **k: "X", None, str, owner=False), "")
        self.assertIsNone(report.critic_summary())  # no scores yet
        self.assertIn("pilot", report.morning_text(None))

    def test_demo_input_only_for_the_demo(self):
        from veliki import makro
        store.kv(self.con, "ulaz", {"state": "aktivan"})
        store.kv(self.con, "walk", {"thr": 0.5})
        self.con.execute("INSERT INTO index_d VALUES (?,?,?,?,?,?,?)", (NOW // D * D, "BTC", "prospektivno", "top",
                                                                         -0.8, 6, None))
        self.con.commit()
        makro._MI.update(ts=0.0)
        self.addCleanup(makro._MI.update, ts=0.0)
        with mock.patch.object(makro, "regime_now", lambda now=None: "neutral"):
            self.assertEqual(makro.demo_regime(NOW)[0], "neutral")             # flag off: nothing
            self.flag(settings.MAKROINF, "shadow")
            makro._MI.update(ts=0.0)
            self.assertEqual(makro.demo_regime(NOW)[0], "neutral")             # shadow: only says it
            self.assertTrue(makro.demo_index(NOW)[0])
            self.flag(settings.MAKROINF, "paper")
            makro._MI.update(ts=0.0)
            self.assertEqual(makro.demo_regime(NOW)[0], "risk_off")
            self.assertEqual(makro.regime_now(NOW), "neutral")                 # the real account's regime unchanged
        from veliki import live
        out = []
        self.assertTrue(live._makroinf_blocks(NOW, out))
        self.assertIn("veliki demo: bez novih ulaza", out[0])
        with open(os.path.join(ROOT, "veliki", "live.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("_makroinf_blocks(now, out):   # 15.11.")
        self.assertIn("if user != settings.PAPER_USER:", src[i - 600:i])     # asked only after the real account left


if __name__ == "__main__":
    unittest.main()
