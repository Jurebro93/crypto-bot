"""11.11. (Jure: "event tokeni s Grokom, prvo shadow/paper", flag event_tokens G19, topics/). Token-aware keyword
matching (GTA6 vs GTA vs GTAV, "$", spaces), clone / main / rug roles (30 min and 30 % exactly), submit_event_topic's
validation (flag, rate limit, active cap, status only forward), the MCP tools' schemas and dispatch with client
attribution, the PumpPortal hook (real time, queued) and the job's catch-up, budgeted search with its daily cost
line, the price 24 h before / at / after an event, the Autopilot card (closed, under "Još", below Dnevnik, owner
only), the kandidati source "event" (never tradeable alone), proposal_rows, the hourly brief part. No network.

    python3 -m unittest tests.test_eventi_offline
"""
import calendar
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from topics import hook, job, match, roles, store, view  # noqa: E402
from trade import settings  # noqa: E402
from tests.test_apui_offline import Base as ApBase, SUMMARY, fake_aplog, fake_equity, history  # noqa: E402

NOW = 1_794_400_000
D = 86400
GTA6, GTA5, GTAV, CLONE = ("G6" + "a" * 40 + "pump", "G5" + "b" * 40 + "pump", "GV" + "c" * 40 + "pump",
                           "CL" + "d" * 40 + "pump")


# ---------------------------------------------------------------------------------------------------------------
class Matching(unittest.TestCase):
    def test_gta6_never_matches_gta_gta5_or_gtav(self):
        kw = ["GTA6"]
        for text in ("GTA6", "GTA 6", "gta-6", "gta_6", "$GTA6", "$gta 6", "Official GTA 6 Coin", "G.T.A 6"):
            self.assertIsNotNone(match.matches(kw, name=text), text)
        for text in ("GTA", "GTA5", "GTA 5", "GTAV", "GTA V", "GTA6INU", "GTA66", "GT A6X"):
            self.assertIsNone(match.matches(kw, name=text), text)

    def test_gta_does_not_match_gtav_unless_listed(self):
        self.assertIsNotNone(match.matches(["GTA"], symbol="$GTA"))
        self.assertIsNotNone(match.matches(["GTA"], name="GTA 6 hype"))     # the whole word gta is there
        for text in ("GTAV", "GTA6", "GTA5", "MEGTA"):
            self.assertIsNone(match.matches(["GTA"], symbol=text), text)
        self.assertIsNotNone(match.matches(["GTA", "GTAV"], symbol="GTAV"))

    def test_dollar_spaces_hyphens_underscores_collapse(self):
        self.assertEqual(match.norm("$GTA 6"), match.norm("gta-6"))
        self.assertEqual(match.norm("GTA_6"), "gta6")
        self.assertIsNotNone(match.matches(["Grand Theft Auto"], name="GrandTheftAuto"))
        self.assertIsNotNone(match.matches(["Grand Theft Auto"], name="grand-theft-auto VI"))
        self.assertIsNone(match.matches(["Grand Theft Auto"], name="Grand Theft"))
        self.assertEqual(match.matches(["GTA6"], symbol="GTA6", name="x", description="y"), ("symbol", "gta6"))
        self.assertEqual(match.matches(["GTA6"], symbol="XYZ", description="the GTA 6 launch coin"),
                         ("description", "gta6"))

    def test_keyword_validation(self):
        for bad in ([], ["a"], ["$"], [" - "], [""], [1], ["x" * 41], ["ok"] * 0 + [f"k{i}x" for i in range(21)]):
            with self.assertRaises(ValueError, msg=bad):
                match.validate(bad)
        self.assertEqual(match.validate(["GTA6", "gta 6", "$GTA6", "Grand Theft Auto"]), ["GTA6", "Grand Theft Auto"])


# ---------------------------------------------------------------------------------------------------------------
class Roles(unittest.TestCase):
    def row(self, tok, age_min=None, sn=None, **kw):
        return {"token": tok, "created_ts": NOW - age_min * 60 if age_min is not None else None, "sniper_pct": sn,
                "rug_level": kw.get("rug"), "liq": kw.get("liq", 0), "mcap": kw.get("mcap", 0),
                "bonded": kw.get("bonded", True), "x": kw.get("x")}

    def test_clone_under_30_min_with_snipers_over_30_pct(self):
        out = roles.classify([self.row("a", 29, 31.0), self.row("b", 31, 31.0), self.row("c", 29, 29.0),
                              self.row("d", 29, 30.0), self.row("e", 29, None), self.row("f", None, 80.0)], NOW)
        self.assertEqual(out["a"][0], "clone")
        self.assertIn("29 min", out["a"][1])
        for t in "bcdef":
            self.assertNotEqual(out[t][0], "clone", t)

    def test_rug_first_then_main_by_liquidity_with_organic_x(self):
        org = {"ts": NOW - 600, "authors15": 5, "bot_share": 0.1}
        out = roles.classify([self.row("r", 300, 5.0, rug="hard", liq=900_000, x=org),
                              self.row("k", 300, rug="risk", liq=800_000),
                              self.row("m", 600, liq=200_000, mcap=900_000, x=org),
                              self.row("o", 900, liq=100_000, mcap=500_000, x=org),
                              self.row("n", 1200, liq=500_000, mcap=2e6, x={"ts": NOW - 600, "authors15": 1})], NOW)
        self.assertEqual({t: r for t, (r, _w) in out.items()},
                         {"r": "rug", "k": "rug", "m": "main", "o": "other", "n": "other"})

    def test_without_any_x_the_oldest_liquid_bonded_token_is_main(self):
        out = roles.classify([self.row("y", 60, liq=50_000, mcap=100_000),
                              self.row("o", 6000, liq=30_000, mcap=80_000),
                              self.row("c", 9000, liq=30_000, mcap=80_000, bonded=False)], NOW)
        self.assertEqual(out["o"][0], "main")
        self.assertIn("bez X-a", out["o"][1])
        self.assertEqual((out["y"][0], out["c"][0]), ("other", "other"))

    def test_organic_x(self):
        self.assertTrue(roles.organic({"ts": NOW, "authors15": 3}, NOW))
        self.assertFalse(roles.organic({"ts": NOW, "authors15": 2}, NOW))
        self.assertTrue(roles.organic({"ts": NOW, "posts60": 10}, NOW))
        self.assertFalse(roles.organic({"ts": NOW, "authors15": 9, "bot_share": 0.6}, NOW))
        self.assertFalse(roles.organic({"ts": NOW - 7 * 3600, "authors15": 9}, NOW))
        self.assertTrue(roles.organic({"ts": NOW, "known_callers": ["ansem"]}, NOW))


# ---------------------------------------------------------------------------------------------------------------
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        env = {"TOPICS_DB": os.path.join(d, "topics.db"), "RANGE_DB": os.path.join(d, "range.db"),
               "RANGE_HYPE_DB": os.path.join(d, "hype.db"), "RUG_DB": os.path.join(d, "rug.db"),
               "SCAN_DB": os.path.join(d, "scan.db")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("BIRDEYE_API_KEY", "HELIUS_API_KEY"):
            os.environ.pop(k, None)
        self._db = settings.DB
        settings.DB = os.path.join(d, "trade.db")
        self.tc = settings.connect()
        settings._FLAG_CACHE.clear()
        hook._STATE.update(at=-1e9, matcher=None)
        hook._Q.clear()
        for obj, name in ((job, "_meter"), (hook, "_start")):   # no meter writes, no writer thread (flush() by hand)
            pm = mock.patch.object(obj, name, lambda *a, **k: None)
            pm.start()
            self.addCleanup(pm.stop)

    def tearDown(self):
        settings.DB = self._db
        settings._FLAG_CACHE.clear()
        hook._STATE.update(at=-1e9, matcher=None)
        hook._Q.clear()
        self.tc.close()
        self.tmp.cleanup()

    def flag(self, mode):
        settings.put(self.tc, "flag:event_tokens", {"mode": mode, "since": NOW})
        settings._FLAG_CACHE.clear()

    def topic(self, name="GTA6", kws=("GTA6", "GTA 6", "Grand Theft Auto", "$GTA6"), **kw):
        return view.submit(name, list(kws), kid="mcp:k1", now=kw.pop("now", NOW), **kw)

    def token(self, tid, tok, role="other", sym=None, created=None, metrics=None, first_seen=NOW):
        con = store.connect()
        store.add_match(con, tid, tok, first_seen, "symbol", "gta6", "test", sym or tok[:4], None, created, metrics)
        con.execute("UPDATE topic_tokens SET role=? WHERE topic_id=? AND token=?", (role, tid, tok))
        con.commit()
        con.close()


class Submit(Base):
    def test_refused_while_the_flag_is_off_except_for_the_owner(self):
        with self.assertRaisesRegex(ValueError, "event_tokens is off"):
            self.topic()
        d = view.submit("GTA6", ["GTA6"], kid="owner", created_by="owner", now=NOW)
        self.assertEqual((d["created_by"], d["status"]), ("owner", "upcoming"))

    def test_upsert_by_name_buzz_trend_and_status_only_forward(self):
        self.flag("shadow")
        d = self.topic(buzz_score=40, event_ts="2026-11-19T15:00:00Z")
        self.assertTrue(d["created"])
        self.assertEqual(d["event_ts"], calendar.timegm((2026, 11, 19, 15, 0, 0)))
        tid = d["id"]
        d2 = view.submit("gta 6", buzz_score=60, status="live", kid="mcp:k1", now=NOW + 900)
        self.assertEqual((d2["id"], d2["created"], d2["status"]), (tid, False, "live"))   # the same topic by its name
        self.assertEqual(len(d2["buzz_history"]), 2)
        self.assertEqual(d2["buzz_trend"], "↑")
        self.assertIn("status upcoming -> live", d2["changed"])
        with self.assertRaisesRegex(ValueError, "only move forward"):
            view.submit("GTA6", status="upcoming", kid="mcp:k1", now=NOW + 1000)
        d3 = view.submit("GTA6", buzz_score=30, kid="mcp:k1", now=NOW + 1100)       # within 5 min: one point
        self.assertEqual(len(d3["buzz_history"]), 2)
        self.assertEqual(d3["buzz_trend"], "↓")
        con = store.connect()
        self.assertEqual(con.execute("SELECT kid, created_by FROM event_topics").fetchone(), ("mcp:k1", "grok"))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM topic_log WHERE kid='mcp:k1'").fetchone()[0], 3)
        con.close()

    def test_validation_active_cap_and_rate_limit(self):
        self.flag("shadow")
        for bad, why in ((dict(name="x", keywords=["GTA6"]), "name"), (dict(name="GTA6"), "needs keywords"),
                         (dict(name="GTA6", keywords=["a"]), "too short"),
                         (dict(name="GTA6", keywords=["GTA6"], buzz_score=101), "buzz_score"),
                         (dict(name="GTA6", keywords=["GTA6"], event_ts=12), "event_ts"),
                         (dict(name="GTA6", keywords=["GTA6"], status="soon"), "status")):
            with self.assertRaisesRegex(ValueError, why):
                view.submit(kid="mcp:k1", now=NOW, **bad)
        with mock.patch.object(view, "MAX_ACTIVE", 2):
            self.topic("A1", ["AAA1"])
            self.topic("A2", ["AAA2"])
            with self.assertRaisesRegex(ValueError, "at most 2 active"):
                self.topic("A3", ["AAA3"])
            view.submit("A1", status="done", kid="mcp:k1", now=NOW)
            self.topic("A3", ["AAA3"])                                     # done no longer counts
        with mock.patch.object(view, "RATE_PER_HOUR", 4):                  # A1, A2, A1 done, A3: 4 writes this hour
            with self.assertRaisesRegex(ValueError, "rate limit"):
                self.topic("A4", ["AAA4"])


class MCP(Base):
    def test_schemas_annotations_and_dispatch_with_attribution(self):
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        s = names["submit_event_topic"]
        self.assertFalse(s["annotations"]["readOnlyHint"])
        self.assertFalse(s["annotations"]["destructiveHint"])
        self.assertEqual(s["inputSchema"]["required"], ["name"])
        self.assertEqual(s["inputSchema"]["properties"]["status"]["enum"], ["upcoming", "live", "done"])
        self.assertIn("GTAV", s["description"])
        for n in ("get_event_topics", "get_event_tokens"):
            self.assertTrue(names[n]["annotations"]["readOnlyHint"])
        self.assertEqual(names["get_event_tokens"]["inputSchema"]["required"], ["topic_id"])
        self.assertIn("submit_event_topic", mcpapi.INSTRUCTIONS)
        d, err = mcpapi._tool("submit_event_topic", {"name": "GTA6", "keywords": ["GTA6"]}, kid="abc")
        self.assertTrue(err)
        self.assertIn("off", d["error"])
        self.flag("shadow")
        d, err = mcpapi._tool("submit_event_topic", {"name": "GTA6", "keywords": ["GTA6", "GTA 6"], "buzz_score": 70,
                                                     "event_ts": NOW + 3 * D}, kid="abc")
        self.assertFalse(err, d)
        con = store.connect()
        self.assertEqual(con.execute("SELECT kid FROM event_topics").fetchone()[0], "mcp:abc")
        con.close()
        self.token(d["id"], GTA6, "main", "GTA6", created=NOW - 5 * D, metrics={"mcap": 400_000, "liq": 60_000})
        lst, err = mcpapi._tool("get_event_topics", {"status": "active"})
        self.assertFalse(err, lst)
        self.assertEqual(lst["topics"][0]["id"], d["id"])
        self.assertEqual(lst["topics"][0]["main"]["token"], GTA6)
        tk, err = mcpapi._tool("get_event_tokens", {"topic_id": d["id"]})
        self.assertFalse(err, tk)
        row = tk["tokens"][0]
        self.assertEqual((row["token"], row["role"], row["market"]["market_cap_usd"]), (GTA6, "main", 400_000))
        for k in ("match", "age_min", "holders", "snipers_pct", "rug", "x", "range", "measure"):
            self.assertIn(k, row)
        self.assertIn("measure_summary", tk)
        bad, err = mcpapi._tool("get_event_tokens", {"topic_id": 999})
        self.assertTrue(err)
        listed = json.loads(mcpapi.rpc(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())[1])
        self.assertTrue({"submit_event_topic", "get_event_topics", "get_event_tokens"}
                        <= {t["name"] for t in listed["result"]["tools"]})


class Hook(Base):
    ROWS = [("M1", NOW, "dev", "GTA 6 Official", "GTA6", 1.0, "s1", "pump"),
            ("M2", NOW, "dev", "GTA 5 Classic", "GTA5", 1.0, "s2", "pump"),
            ("M3", NOW, "dev", "Grand Theft Auto VI", "GTAVI", 1.0, "s3", "migration")]

    def test_flag_off_nothing_is_matched(self):
        self.assertEqual(hook.launches(self.ROWS), 0)

    def test_new_tokens_are_matched_in_real_time_and_written_by_the_queue(self):
        self.flag("shadow")
        tid = self.topic()["id"]
        self.assertEqual(hook.launches(self.ROWS), 2)
        self.assertEqual(hook.flush(), 2)
        con = store.connect()
        got = {r[0]: r[1:] for r in con.execute("SELECT token, match_field, via, created_ts FROM topic_tokens "
                                                "WHERE topic_id=?", (tid,))}
        con.close()
        self.assertEqual(got, {"M1": ("symbol", "pumpportal_create", NOW), "M3": ("name", "pumpportal_migration", None)})

    def test_the_feed_calls_the_hook(self):
        from live import pumpportal, store as lstore
        self.flag("shadow")
        self.topic()
        lcon = lstore.connect(os.path.join(self.tmp.name, "hype.db"))
        feed = pumpportal.Feed(lcon, log=lambda *_: None)
        feed.take({"txType": "create", "mint": "M9", "signature": "s9", "name": "gta-6", "symbol": "SIX"}, now=NOW)
        self.assertEqual(feed.flush(NOW + 2, force=True), 1)
        lcon.close()
        self.assertEqual(len(hook._Q), 1)
        self.assertEqual(hook._Q[0][1], "M9")


class Net:
    def __init__(self, results=None):
        self.results, self.asked, self.gt = results or {}, [], []

    def dex_search(self, q):
        self.asked.append(q)
        return self.results.get(q, [])

    def bird_search(self, q):
        return None

    def gt_minutes(self, pool, start, end):
        self.gt.append(pool)
        return [(int(start) + 60 * i, 1.0, 1.0, 1.0, 3.0, 10.0) for i in range(5)]

    def helius_snipers(self, mint):
        raise AssertionError("no Helius in this test")


def dpair(tok, sym, chain="solana", liq=80_000.0, mc=900_000.0, created=NOW - 10 * D):
    return {"chainId": chain, "baseToken": {"address": tok, "symbol": sym, "name": sym}, "priceUsd": "0.0009",
            "marketCap": mc, "dexId": "pumpswap", "pairAddress": "P" + tok[:8], "liquidity": {"usd": liq},
            "volume": {"h1": 20_000, "h24": 300_000}, "priceChange": {"h1": 3.0}, "pairCreatedAt": created * 1000}


class Job(Base):
    def test_flag_off_the_job_ends_at_once(self):
        self.assertEqual(job.once(now=NOW, net=Net()), "off")
        self.assertFalse(os.path.exists(os.environ["TOPICS_DB"]))

    def test_search_keeps_token_aware_matches_within_the_daily_cap_and_logs_the_cost(self):
        self.flag("shadow")
        t1 = self.topic()["id"]
        self.topic("Pepe Movie", ["PEPEMOVIE"])
        net = Net({"GTA6": [dpair(GTA6, "GTA6"), dpair(GTA5, "GTA5"), dpair(GTAV, "GTAV"),
                            dpair("E" * 40, "GTA6", chain="ethereum")]})
        logs = []
        with mock.patch.object(job, "DEX_DAY", 1):
            job.once(now=NOW, net=net, log=logs.append, rug={}, x={})
            self.assertEqual(len(net.asked), 1)                            # the cap: one search today
            job.once(now=NOW + 700, net=net, log=logs.append, rug={}, x={})
            self.assertEqual(len(net.asked), 1)
        con = store.connect()
        toks = {r[0]: r[1:] for r in con.execute("SELECT token, via, match_kw FROM topic_tokens")}
        m = json.loads(con.execute("SELECT metrics FROM topic_tokens WHERE token=?", (GTA6,)).fetchone()[0])
        con.close()
        self.assertEqual(toks, {GTA6: ("dexscreener_search", "gta6")})    # GTA5, GTAV and the Ethereum pair out
        self.assertEqual((m["mcap"], m["liq"], m["bonded"]), (900_000.0, 80_000.0, True))
        day = time.strftime("%Y-%m-%d", time.gmtime(NOW))
        with mock.patch.object(job, "DEX_DAY", 1):
            job.once(now=NOW + D, net=net, log=logs.append, rug={}, x={})
        line = [x for x in logs if x.startswith("eventi trošak")]
        self.assertEqual(line, [f"eventi trošak ({day}): dexscreener 1/1, birdeye 0/{job.BIRD_DAY}, gt 0/{job.GT_DAY}, "
                                f"helius 0/{job.HELIUS_DAY} kredita"])
        tk = view.tokens(t1, now=NOW, rug={}, x={}, ranges={})
        self.assertEqual(tk["tokens"][0]["role"], "main")                 # no X anywhere: the oldest liquid bonded one

    def test_catch_up_from_stored_launches_and_roles(self):
        from live import store as lstore
        self.flag("shadow")
        lcon = lstore.connect(os.environ["RANGE_HYPE_DB"])
        lcon.execute("INSERT INTO live_launches VALUES (?,?,?,?,?,?,?,?)", (CLONE, NOW - 10 * 60, "d", "GTA6 2.0", "GTA6",
                                                                             1.0, "x1", "pump"))
        lcon.execute("INSERT INTO live_launches VALUES (?,?,?,?,?,?,?,?)", (GTA5, NOW - 600, "d", "GTA5", "GTA5", 1.0, "x2",
                                                                             "pump"))
        lcon.commit()
        tid = self.topic()["id"]
        hc = sqlite3.connect(os.environ["RANGE_HYPE_DB"])
        hc.execute("CREATE TABLE IF NOT EXISTS hype_details (token TEXT, ts INTEGER, extra TEXT, PRIMARY KEY (token, ts))")
        hc.execute("INSERT INTO hype_details VALUES (?,?,?)", (CLONE, NOW, json.dumps(
            {"pumpfun": {"snipersOwnedPercent": 25.0, "bundlerOwnedPercent": 12.0}})))
        hc.commit()
        hc.close()
        job.once(now=NOW, net=Net(), log=lambda *_: None, rug={}, x={})   # the new topic: everything stored
        lcon.execute("INSERT INTO live_launches VALUES (?,?,?,?,?,?,?,?)", ("NEW1", NOW + 30, "d", "gta_6", "SIX", 1.0,
                                                                             "x3", "pump"))
        lcon.commit()
        lcon.close()
        job.once(now=NOW + 60, net=Net(), log=lambda *_: None, rug={}, x={})   # then only the newer rows
        con = store.connect()
        got = dict(con.execute("SELECT token, role FROM topic_tokens WHERE topic_id=?", (tid,)))
        con.close()
        self.assertEqual(set(got), {CLONE, "NEW1"})
        self.assertEqual(got[CLONE], "clone")                              # 10 min old, snipers + bundlers 37 %

    def test_price_before_at_and_after_the_event_and_the_summary(self):
        self.flag("shadow")
        ev = NOW - 2 * D
        tid = self.topic(event_ts=ev)["id"]
        self.token(tid, GTA6, "main", created=ev - 10 * D, metrics={"pool": "POOL1", "mcap": 1e6, "price": 1.0})
        self.token(tid, GTA5, "other", created=ev - 10 * D)
        self.token(tid, CLONE, "other", created=ev + 3600)                 # did not exist 24 h before nor at the event
        prices = {(GTA6, ev - D): (1.0, 1e6, "range.db snimka"), (GTA6, ev): (2.0, 2e6, "range.db snimka"),
                  (GTA5, ev - D): (1.0, None, "hype.db token_pulse"), (GTA5, ev): (1.0, None, "hype.db token_pulse"),
                  (GTA5, ev + D): (1.2, None, "hype.db token_pulse"), (CLONE, ev + D): (5.0, None, "x")}
        net = Net()
        con = store.connect()
        n = job.measure_pass(con, NOW, net, lambda *_: None, price_fn=lambda tok, ts: prices.get((tok, ts)))
        con.commit()
        self.assertEqual(n, 7)                                             # GTA6 after from GeckoTerminal
        self.assertEqual(net.gt, ["POOL1"])
        row = con.execute("SELECT after_px, after_src, after_mc FROM topic_measure WHERE token=?", (GTA6,)).fetchone()
        self.assertEqual(row, (3.0, "GeckoTerminal minuta (eventi)", 3e6))
        self.assertEqual(con.execute("SELECT before_px, at_px, note FROM topic_measure WHERE token=?", (CLONE,)).fetchone(),
                         (None, None, "nije:at,nije:before"))
        job.measure_pass(con, NOW + 60, net, lambda *_: None, price_fn=lambda tok, ts: None)
        self.assertEqual(net.gt, ["POOL1"])                                # one GeckoTerminal try per point
        con.close()
        s = view.tokens(tid, now=NOW, rug={}, x={}, ranges={})["measure_summary"]
        self.assertEqual((s["n_before_at"], s["run_up_pct_median"]), (2, 50.0))     # +100 % and 0 %
        self.assertEqual((s["n_at_after"], s["after_pct_median"]), (2, 35.0))       # +50 % and +20 %
        self.assertEqual(s["exit_at_event_better"], 0.0)


class Outputs(Base):
    def test_proposal_rows_main_tokens_of_events_in_the_next_days(self):
        self.flag("shadow")
        soon = self.topic(event_ts=NOW + 2 * D)["id"]
        late = self.topic("Later", ["LATERX"], event_ts=NOW + 20 * D)["id"]
        past = self.topic("Past", ["PASTX"], event_ts=NOW - D)["id"]
        self.token(soon, GTA6, "main", "GTA6", metrics={"mcap": 5e5, "liq": 7e4})
        self.token(soon, GTA5, "other")
        self.token(late, GTAV, "main")
        self.token(past, CLONE, "main")
        rows = view.proposal_rows(NOW, days=7)
        self.assertEqual(rows, [{"token": GTA6, "symbol": "GTA6", "topic": "GTA6", "topic_id": soon,
                                 "event_ts": NOW + 2 * D, "role": "main", "mcap": 5e5, "liq": 7e4}])
        self.assertEqual({r["token"] for r in view.proposal_rows(NOW, days=30)}, {GTA6, GTAV})
        view.submit("GTA6", status="done", kid="mcp:k1", now=NOW)
        self.assertEqual(view.proposal_rows(NOW, days=7), [])

    def test_kandidati_event_source_is_shown_but_never_tradeable_alone(self):
        from tests.test_kandidati_offline import FakeSources, live
        from ui import kandidati
        S = FakeSources()
        S.events = lambda now: [{"token": GTA6, "symbol": "GTA6", "topic_id": 1, "topic": "GTA6", "role": "main",
                                 "event_ts": NOW + D, "buzz_score": 70, "buzz_trend": "↑", "first_seen": NOW - 600},
                                {"token": GTA5, "symbol": "GTA5", "topic_id": 1, "topic": "GTA6", "role": "other",
                                 "event_ts": NOW + D, "buzz_score": 70, "buzz_trend": "↑", "first_seen": NOW - 600}]
        S.c = [(GTA5, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "GTA5", live())]
        S.mk = {GTA6: live()}
        rows, _meta = kandidati.build(NOW, S)
        got = {r["token"]: r for r in rows}
        self.assertEqual(got[GTA6]["source_kinds"], ["event"])
        self.assertEqual(got[GTA6]["confluence"], 1)
        self.assertFalse(got[GTA6]["tradeable"])
        self.assertTrue(any("nikad pravi novac" in w for w in got[GTA6]["why_not"]))
        self.assertEqual(got[GTA6]["sources"]["event"]["topics"][0]["role"], "main")
        self.assertIn("event", got[GTA5]["source_kinds"])
        self.assertFalse(any("nikad pravi novac" in w for w in got[GTA5]["why_not"]))   # a caller too: the old rules
        mrng = {"range": {"watch_source": "market"}}
        self.assertTrue(kandidati.paper_only(mrng))
        self.assertFalse(kandidati.paper_only({"range": {"watch_source": "signal"}}))
        self.assertFalse(kandidati.paper_only({"range": {"watch_source": "market"}, "caller": {}}))

    def test_hourly_brief_part(self):
        self.assertEqual(view.brief_part(NOW), {"flag_mode": "off", "topics": []})
        self.flag("shadow")
        tid = self.topic(buzz_score=50)["id"]
        self.token(tid, GTA6, "main", "GTA6")
        d = view.brief_part(NOW)
        self.assertEqual((d["topics"][0]["id"], d["topics"][0]["main"]["token"], d["topics"][0]["n_tokens"]),
                         (tid, GTA6, 1))
        from events import brief
        self.assertIn("event_topics", brief.build(now=NOW))


class Card(ApBase):
    """The Autopilot page (the fakes of tests/test_apui_offline): "Eventi" closed under "Još", below Dnevnik."""

    def setUp(self):
        super().setUp()
        d = self.tmp.name
        p = mock.patch.dict(os.environ, {"TOPICS_DB": os.path.join(d, "topics.db"), "RANGE_DB": os.path.join(d, "range.db"),
                                         "RANGE_HYPE_DB": os.path.join(d, "hype.db")})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(settings._FLAG_CACHE.clear)
        settings._FLAG_CACHE.clear()

    def test_closed_under_jos_below_dnevnik_owner_only(self):
        from ui import pravitrade
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        _, body = pravitrade.page({}, "Jure")
        self.assertNotIn("id=eventi", body)                                 # flag off: no card
        settings.put(self.con, "flag:event_tokens", {"mode": "shadow", "since": NOW})
        settings._FLAG_CACHE.clear()
        tid = view.submit("GTA6", ["GTA6"], event_ts=NOW + D, buzz_score=40, kid="mcp:k1", now=NOW)["id"]
        view.submit("GTA6", buzz_score=80, kid="mcp:k1", now=NOW + 900)
        Base.token(self, tid, GTA6, "main", "GTA6", metrics={"mcap": 450_000})
        Base.token(self, tid, CLONE, "clone", "GTA6X")
        _, body = pravitrade.page({}, "Jure")
        at = body.index("id=eventi")
        tag = body[body.rindex("<details", 0, at):body.index(">", at)]
        self.assertNotIn(" open", tag)                                      # closed
        self.assertGreater(at, body.index(">Još<"))                          # under "Još"
        self.assertGreater(at, body.index("id=dnevnik"))                     # nothing above Dnevnik
        card = body[body.rindex("<details", 0, at):]
        self.assertIn("Eventi", card)
        self.assertIn("glavni", card)
        self.assertIn("klon", card)
        self.assertIn("450k $", card)
        self.assertIn("↑", card)
        h2s = re.findall(r"<h2[^>]*>", body)
        self.assertEqual([h for h in h2s if 'data-sec=""' not in h and "nosec" not in h], [])   # no chip bar
        self.assertNotIn("id=eventi", pravitrade.page({}, "Ivan")[1])       # owner only


if __name__ == "__main__":
    unittest.main()
