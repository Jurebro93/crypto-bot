"""Audit 9.11.2026, group 'izvori' (sources): the fixes for findings P2, P3, P20-P25, P29, P35, P36, P55-P57.
Offline: no network, temp databases only."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dexscreener import client  # noqa: E402
from event_calendar import http  # noqa: E402
from hype import sources  # noqa: E402
from kol import chainwatch, collect, converge, minute, store as kstore, xhook  # noqa: E402
from league import copy  # noqa: E402
from tg import poll, store as tstore  # noqa: E402
from topcheck import holders, safety  # noqa: E402
from wallets import dokazani, store as wstore  # noqa: E402
import run_kol  # noqa: E402
import run_top  # noqa: E402

CA = "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz"
TID = "1793556384590000000"
NOW = int(time.time()) // 60 * 60
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KCFG = json.load(open(os.path.join(ROOT, "kol", "config.json")))


def _locked(*a, **k):
    raise sqlite3.OperationalError("database is locked")


class DexLive(unittest.TestCase):
    def test_tokens_live_uses_a_short_cache_and_tokens_keeps_60s(self):   # P2
        seen = []

        def get_json(url, params=None, ttl=None, **k):
            seen.append(ttl)
            return []
        with mock.patch.object(client.http, "get_json", get_json), mock.patch.object(client._FAST, "wait", lambda: None):
            client.tokens("solana", [CA])
            client.tokens_live("solana", [CA])
            client.tokens_live("solana", [CA], ttl=1)          # never under 2 s: the 300/min limit is shared per IP
        self.assertEqual(seen, [client.CACHE_TTL, client.LIVE_TTL, 2])
        self.assertTrue(2 <= client.LIVE_TTL <= 5)
        self.assertEqual(client.CACHE_TTL, 60)


class XHookSpool(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "kol.db")
        kstore.connect(self.db).close()
        self.tw = {"id": "9001", "text": f"aping {CA} now", "createdAt": "Thu Nov 05 12:00:00 +0000 2026",
                   "author": {"userName": "caller", "followers": 40000}}

    def test_locked_db_spools_and_collect_drains(self):   # P3
        logs = []
        with mock.patch.object(kstore, "connect", _locked):
            self.assertEqual(xhook.ingest({"tweets": [self.tw]}, kol_db=self.db, now=NOW, log=logs.append), 0)   # no raise: 200
        files = os.listdir(xhook.spool_dir(self.db))
        self.assertEqual(len(files), 1)
        self.assertTrue(any("spool" in s for s in logs))
        con = kstore.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 0)
        con.close()
        with mock.patch.object(copy, "WAKE", os.path.join(self.d, ".copy_wake")):
            self.assertEqual(xhook.drain(self.db, now=NOW, log=logs.append), 1)
            self.assertTrue(copy.woke_since(0))                                  # P25: a new call wakes the copy loop
        self.assertEqual(os.listdir(xhook.spool_dir(self.db)), [])
        con = kstore.connect(self.db)
        self.assertEqual(con.execute("SELECT handle, token, source FROM calls").fetchall(), [("caller", CA, "x_hook")])
        con.close()
        self.assertEqual(xhook.drain(self.db, now=NOW, log=logs.append), 0)      # empty spool

    def test_collect_drains_although_its_own_connection_wrote_first(self):   # review izvori: commit before drain
        with mock.patch.object(kstore, "connect", _locked):
            xhook.ingest({"tweets": [self.tw]}, kol_db=self.db, now=NOW, log=lambda s: None)
        con = kstore.connect(self.db)
        orig = sqlite3.connect

        def webhook(c, hype_db=None):            # from_webhook: INSERT without commit, as the real one does
            c.execute("INSERT INTO kv VALUES ('tw_pending', '[]')")
            return 0
        with mock.patch.object(kstore, "DB", self.db), mock.patch.object(run_kol.collect, "from_webhook", webhook), \
                mock.patch.object(run_kol.collect, "from_hype_cache", lambda c, hype_db=None: 0), \
                mock.patch.object(run_kol.collect, "from_telegram", lambda c, tg_db=None: 0), \
                mock.patch.object(run_kol.collect, "from_chain", lambda c, hype_db=None: 0), \
                mock.patch.object(chainwatch, "drain", lambda *a, **k: 0), mock.patch.object(copy, "wake"), \
                mock.patch.object(sqlite3, "connect", lambda p, timeout=60, **k: orig(p, timeout=1, **k)), \
                mock.patch("builtins.print"):
            self.assertEqual(run_kol.cmd_collect(None, con=con), 1)   # the spooled call, not 'database is locked'
        self.assertEqual(os.listdir(xhook.spool_dir(self.db)), [])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 1)
        con.close()

    def test_two_spools_in_the_same_millisecond_keep_both(self):   # review izvori
        with mock.patch.object(kstore, "connect", _locked):
            xhook.ingest({"tweets": [self.tw]}, kol_db=self.db, now=NOW, log=lambda s: None)
            xhook.ingest({"tweets": [dict(self.tw, id="9002")]}, kol_db=self.db, now=NOW, log=lambda s: None)
        self.assertEqual(len(os.listdir(xhook.spool_dir(self.db))), 2)

    def test_drain_keeps_the_file_while_still_locked(self):
        with mock.patch.object(kstore, "connect", _locked):
            xhook.ingest({"tweets": [self.tw]}, kol_db=self.db, now=NOW, log=lambda s: None)
            self.assertEqual(xhook.drain(self.db, now=NOW, log=lambda s: None), 0)
        self.assertEqual(len(os.listdir(xhook.spool_dir(self.db))), 1)

    def test_new_call_wakes_copy_and_a_repeat_does_not(self):   # P25
        with mock.patch.object(copy, "wake") as w:
            xhook.ingest({"tweets": [self.tw]}, kol_db=self.db, now=NOW, log=lambda s: None)
            w.assert_called_once()
        with mock.patch.object(copy, "wake") as w:
            xhook.ingest({"tweets": [self.tw]}, kol_db=self.db, now=NOW, log=lambda s: None)
            w.assert_not_called()


class ChainSpool(unittest.TestCase):
    def test_locked_hype_db_spools_then_drains_and_prunes_hourly(self):   # P21
        d = tempfile.mkdtemp()
        db = os.path.join(d, "hype.db")
        tx = {"type": "SWAP", "signature": "s1", "timestamp": NOW, "feePayer": "W1",
              "tokenTransfers": [{"fromUserAccount": "POOL", "toUserAccount": "W1", "mint": CA, "tokenAmount": 10}],
              "nativeTransfers": [{"fromUserAccount": "W1", "toUserAccount": "POOL", "amount": 1_000_000_000}]}
        with mock.patch.object(chainwatch.sqlite3, "connect", _locked), mock.patch.object(copy, "wake") as w:
            n = chainwatch.ingest([tx], db)
            self.assertGreaterEqual(n, 1)                                        # no raise: the dashboard answers 200
            w.assert_not_called()                                                # nothing in hype.db yet to copy
        self.assertEqual(len(os.listdir(chainwatch.spool_dir(db))), 1)
        chainwatch._PRUNED["ts"] = 0.0
        with mock.patch.object(copy, "wake") as w:
            self.assertGreaterEqual(chainwatch.drain(db, log=lambda *a, **k: None), 1)
            w.assert_called()
        self.assertEqual(os.listdir(chainwatch.spool_dir(db)), [])
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM chain_trades").fetchone()[0], 1)
        # retention runs at most once an hour, not in every webhook handler
        con.execute("INSERT INTO chain_trades VALUES ('old', 'W1', 'M', 'buy', ?, 1.0)", (NOW - 400 * 86400,))
        con.commit()
        con.close()
        tx2 = dict(tx, signature="s2")
        with mock.patch.object(copy, "wake"):
            chainwatch.ingest([tx2], db)
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM chain_trades WHERE sig='old'").fetchone()[0], 1)
        con.close()
        chainwatch._PRUNED["ts"] = 0.0
        with mock.patch.object(copy, "wake"):
            chainwatch.ingest([dict(tx, signature="s3")], db)
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM chain_trades WHERE sig='old'").fetchone()[0], 0)
        con.close()
        self.assertEqual(chainwatch.ingest([{"type": "OTHER"}], db), 0)
        # review izvori: the drain the webhook thread runs after its own write waits 10 s at most, not 60
        seen = []
        orig = chainwatch.ingest

        def spy(payload, hype_db=None, _spool=True, timeout=None):
            seen.append((_spool, timeout))
            return orig(payload, hype_db, _spool, timeout)
        with mock.patch.object(chainwatch.sqlite3, "connect", _locked):
            chainwatch.ingest([dict(tx, signature="s4")], db)
        with mock.patch.object(chainwatch, "ingest", spy), mock.patch.object(copy, "wake"):
            chainwatch.drain(db, log=lambda *a, **k: None, timeout=10)
        self.assertEqual(seen, [(False, 10)])


class KolMentionsTime(unittest.TestCase):
    def test_ts_is_the_post_time_from_the_status_link_and_wakes_copy(self):   # P20, P25
        d = tempfile.mkdtemp()
        db = os.path.join(d, "h.db")
        text = f"{TID} https://x.com/kol1/status/{TID} {TID} 1793543723000 en aping $GTA6 {CA}"
        with mock.patch.object(copy, "wake") as w:
            n = sources.ingest_kol_event({"event": {"author": {"username": "kol1"}, "text": text}}, db, now=NOW)
            w.assert_called_once()
        self.assertEqual(n, 1)
        con = sqlite3.connect(db)
        ts, handle = con.execute("SELECT ts, handle FROM kol_mentions").fetchone()
        self.assertEqual(ts, collect.snowflake_ts(TID))                         # not the webhook arrival time
        self.assertEqual(handle, "kol1")
        # no link in the payload: the arrival time, as before; a ticker-only post does not wake the copy loop
        with mock.patch.object(copy, "wake") as w:
            sources.ingest_kol_event({"author": {"username": "kol2"}, "text": f"gm {CA}"}, db, now=NOW)
            sources.ingest_kol_event({"author": {"username": "kol3"}, "text": "gm $TICK"}, db, now=NOW)
            w.assert_called_once()
        rows = dict(con.execute("SELECT handle, ts FROM kol_mentions WHERE handle != 'kol1'").fetchall())
        self.assertEqual(rows, {"kol2": NOW, "kol3": NOW})
        con.close()


class ConvergeCurrent(unittest.TestCase):
    def test_saved_row_is_the_current_state_not_the_peak(self):   # P22
        con = kstore.connect(":memory:")
        r = {"last_ts": NOW - 600, "first_ts": NOW - 900, "score": 80.0, "n_x": 3, "n_tg": 1, "n_chain": 2, "n_other": 4,
             "platforms": ["x", "tg"], "handles": ["a", "b", "c"], "kol_selling": 0}
        converge.save(con, {"TOK": r}, NOW - 600)
        r2 = dict(r, last_ts=NOW, score=25.0, n_x=1, n_tg=0, n_chain=0, n_other=1, handles=["a"])
        converge.save(con, {"TOK": r2}, NOW)
        row = con.execute("SELECT ts, score, n_x, n_tg, n_chain, n_other, handles FROM converge WHERE token='TOK'").fetchone()
        self.assertEqual(row, (NOW, 25.0, 1, 0, 0, 1, json.dumps(["a"])))


class MinuteStats(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.mc = minute.connect(os.path.join(self.d, "minute.db"))
        self.kc = kstore.connect(os.path.join(self.d, "kol.db"))
        os.environ["MINUTE_DB"] = os.path.join(self.d, "minute.db")

    def tearDown(self):
        self.mc.close()
        self.kc.close()
        os.environ.pop("MINUTE_DB", None)

    def _path(self, tid, tok, handle, ts, t10=2, sl=None):
        self.mc.execute("INSERT OR REPLACE INTO call_path VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (tid, tok, handle, ts, 1.0, 30, 50000, 0.1, 0.1, 0.1, -0.05, 0.05, 1, t10, None, None, None, sl,
                         1, None, NOW))

    def test_handle_stats_count_tokens_not_posts(self):   # P23
        for i in range(5):                                       # one token posted five times
            self._path(f"t{i}", "TOK", "spam", NOW - 3600 + i * 60)
        self._path("u1", "A", "good", NOW - 3600)
        self._path("u2", "B", "good", NOW - 3000, t10=None, sl=4)
        st = dict(minute.handle_stats(self.mc, 14, NOW))
        self.assertEqual((st["spam"]["n"], st["spam"]["n_posts"], st["spam"]["hit10"]), (1, 5, 1.0))
        self.assertEqual((st["good"]["n"], st["good"]["n_posts"], st["good"]["hit10"]), (2, 2, 0.5))
        self.assertEqual([h for h, _ in minute.handle_stats(self.mc, 14, NOW)], ["good", "spam"])   # by distinct tokens
        hot = minute.hot(self.mc, self.kc, dict(KCFG, minute=dict(KCFG["minute"], hot_min_n=2)), NOW,
                         wallet_db=os.path.join(self.d, "nema.db"))
        self.assertEqual(hot["x"], [])                            # 5 posts of one token do not make the hot list

    def test_fetch_errors_mark_pool_or_wait_an_hour(self):   # P24
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('GONE', 'P1', 1e6)")
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('BUSY', 'P2', 1e6)")
        self.kc.execute("INSERT INTO kols (handle, bot) VALUES ('a', 0)")
        self.kc.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,'call')",
                            [("1", "GONE", "a", NOW - 7200), ("2", "GONE", "b", NOW - 7000), ("3", "BUSY", "a", NOW - 7200)])
        self.kc.commit()

        def fetch(pool, s, e):
            if pool == "P1":
                raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
            raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        logs = []
        t, n, left = minute.run(self.kc, self.mc, KCFG, NOW, fetch=fetch, log=logs.append)
        self.assertEqual((t, n), (0, 0))
        bad = dict(self.mc.execute("SELECT tweet_id, bad FROM call_path").fetchall())
        self.assertEqual(bad, {"1": "pool", "2": "pool"})           # 404: recorded, never fetched again
        self.assertEqual(minute.due(self.kc, self.mc, minute.config(KCFG), NOW + 60), {})       # BUSY waits
        self.assertIn("BUSY", minute.due(self.kc, self.mc, minute.config(KCFG), NOW + minute.RETRY_S + 1))
        self.assertEqual(minute.hot(self.mc, self.kc, KCFG, NOW, wallet_db=os.path.join(self.d, "nema.db"))["x"], [])

    def test_gecko_403_pauses_every_process(self):   # P24 (event_calendar/http)
        url = "https://api.geckoterminal.com/api/v2/networks/solana/pools/x/ohlcv/minute"
        req = http.urllib.request.Request(url)

        def boom(*a, **k):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        with mock.patch.object(http.urllib.request, "urlopen", boom), mock.patch.object(http, "_pace", lambda u: None), \
                mock.patch.object(http, "limited") as lim:
            with self.assertRaises(urllib.error.HTTPError):
                http._fetch(req, 5, retries=0)
            lim.assert_called_once_with(url, http.SHARED_403_PAUSE)
        with mock.patch.object(http.urllib.request, "urlopen", boom), mock.patch.object(http, "_pace", lambda u: None), \
                mock.patch.object(http, "limited") as lim:
            with self.assertRaises(urllib.error.HTTPError):
                http._fetch(http.urllib.request.Request("https://api.dexscreener.com/x"), 5, retries=0)
            lim.assert_not_called()                                   # only the shared-limit host


class TopcheckGates(unittest.TestCase):
    def _rc(self, top10=None):
        return {"mint_auth": None, "freeze_auth": None, "rugged": False, "launchpad": None, "lp_locked": 100.0,
                "has_market": True, "top10": top10, "insiders": 0, "dev_pct": 1.0, "creator_tokens": 1, "holders": 100,
                "fee": 0, "perm_delegate": False, "non_transferable": False, "transfer_hook": False,
                "frozen_default": False, "danger": [], "decimals": 6, "supply": 1}

    def test_unknown_holders_is_not_prolazi(self):   # P36
        j = safety.judge("X", self._rc(None), {"ok": True, "ratio": 0.98})
        self.assertEqual(j["verdict"], "oprez")
        self.assertEqual(j["checks"]["holderi"][0], "warn")
        self.assertIn("nepoznat", j["checks"]["holderi"][1])
        light = safety.summarize_light({"lpLockedPct": 0, "risks": []})
        self.assertNotEqual(safety.judge("Xpump", light, {"ok": True, "ratio": 0.98})["verdict"], "prolazi")
        self.assertEqual(safety.judge("X", self._rc(20.0), {"ok": True, "ratio": 0.98})["verdict"], "prolazi")

    def test_full_filter_flags_become_a_warn_and_fill_missing_top10(self):   # P29
        full = {"verdict": "OPREZ", "data": {"hard_fails": [], "flags": ["snajperi kupili 25% u prvih ~8 s (7 walleta)"],
                                             "score": 60, "holders": {"top10_pct": 59.0},
                                             "launch": {"bundle_pct": 5.0, "sniper_pct": 25.0}}}
        j = safety.judge("X", self._rc(20.0), {"ok": True, "ratio": 0.98}, full)
        self.assertEqual(j["verdict"], "oprez")
        self.assertEqual(j["checks"]["rugfilter"][0], "warn")
        self.assertIn("snajperi", j["checks"]["rugfilter"][1])
        self.assertEqual(j["checks"]["holderi"], ["ok", "top 10 holdera drži 20%"])     # RugCheck top10 wins when known
        j = safety.judge("X", self._rc(None), {"ok": True, "ratio": 0.98}, full)
        self.assertEqual(j["checks"]["holderi"][0], "warn")
        self.assertIn("59%", j["checks"]["holderi"][1])
        self.assertIn("rug filter", j["checks"]["holderi"][1])
        ok = {"verdict": "PROLAZI", "data": {"hard_fails": [], "flags": []}}
        self.assertEqual(safety.judge("X", self._rc(20.0), {"ok": True, "ratio": 0.98}, ok)["verdict"], "prolazi")
        # run_top passes the flags and the numbers on, not only the hard fails
        d = run_top._full_data({"hard_fails": [], "flags": ["x"], "score": 61, "holders": {"top10_pct": 59},
                                "launch": {"bundle_pct": 5, "sniper_pct": 25, "bundle": [1]}, "cluster": {"holding_pct": 3}})
        self.assertEqual(d, {"hard_fails": [], "flags": ["x"], "score": 61, "holders": {"top10_pct": 59},
                             "launch": {"bundle_pct": 5, "sniper_pct": 25}, "cluster": {"holding_pct": 3}})
        self.assertEqual(run_top._full_data({})["holders"], {"top10_pct": None})

    def test_pumpfun_shape_from_topcheck_and_rug_db(self):   # P56
        tc = {"A": {"rc": {"top10": 41.0, "dev_pct": 3.0, "insiders": 2.0}}, "B": {"rc": None}}
        rug = {"A": (12.0, 25.0, 59.0), "C": (None, 8.0, 30.0)}
        got = holders.pumpfun_shape(["A", "B", "C", "D"], tc=tc, rug=rug)
        self.assertEqual(set(got), {"A", "C"})
        self.assertEqual(got["A"]["top10HoldersPercent"], 41.0)         # RugCheck (pools excluded) before rug.db
        self.assertEqual((got["A"]["bundlerOwnedPercent"], got["A"]["snipersOwnedPercent"], got["A"]["devHoldingsPercent"]),
                         (12.0, 25.0, 3.0))
        self.assertEqual(got["C"]["top10HoldersPercent"], 30.0)
        self.assertIsNone(got["C"]["bundlerOwnedPercent"])              # unknown stays None, never a healthy 0
        self.assertEqual(holders.pumpfun_shape([], tc=tc, rug=rug), {})
        self.assertEqual(holders._rug_rows(["A"], os.path.join(tempfile.mkdtemp(), "nema.db")), {})


class TelegramFollowed(unittest.TestCase):
    def test_followed_channel_is_read_whatever_its_status(self):   # P35
        d = tempfile.mkdtemp()
        con = tstore.connect(os.path.join(d, "tg.db"))
        cfg = {"hot_hours": 1, "hot_score": 70, "poll_hot_s": 30, "poll_active_s": 300, "poll_quiet_s": 1800,
               "recheck_dead_d": 14, "validate_per_tick": 0, "validate_every_s": 10, "poll_followed_s": 2}
        tstore.add_candidates(con, ["cand", "deadch", "act"], "x", NOW - 7200)
        con.execute("UPDATE channels SET status='dead', checked_ts=? WHERE name='deadch'", (NOW - 60,))
        con.execute("UPDATE channels SET status='active', last_poll=? WHERE name='act'", (NOW,))
        con.commit()
        with mock.patch.object(poll, "followed_channels", lambda: {"cand", "deadch", "typed"}):
            poll._PACE["validate_ts"] = NOW
            _, due = poll.due(con, cfg, {}, NOW)
        self.assertEqual(set(due), {"cand", "deadch", "typed"})           # not 'act' (polled just now)
        st = dict(con.execute("SELECT name, status FROM channels"))
        self.assertEqual(st["typed"], "candidate")                       # typed as tg:typed, unknown to tg.db before
        self.assertEqual(con.execute("SELECT found_via FROM channels WHERE name='typed'").fetchone()[0], "follow")
        with mock.patch.object(poll, "followed_channels", lambda: set()):
            poll._PACE["validate_ts"] = NOW
            _, due = poll.due(con, cfg, {}, NOW)
        self.assertEqual(due, [])                                        # unchanged schedule without follows
        # review izvori: a followed name t.me refused max_fails times (typo, private) is read every poll_active_s,
        # not every 2 s for ever; one real read (visit) makes it active again and back in the 2-second set
        con.execute("UPDATE channels SET fails=3, last_poll=? WHERE name='deadch'", (NOW - 10,))
        con.execute("UPDATE channels SET fails=1, status='dead', last_poll=? WHERE name='cand'", (NOW - 10,))
        con.commit()
        with mock.patch.object(poll, "followed_channels", lambda: {"cand", "deadch"}):
            poll._PACE["validate_ts"] = NOW
            _, due = poll.due(con, dict(cfg, max_fails=3), {}, NOW)
            self.assertEqual(due, ["cand"])
            _, due = poll.due(con, dict(cfg, max_fails=3), {}, NOW + 300)
            self.assertLessEqual({"cand", "deadch"}, set(due))          # ('act' is due by then too: 300 s active)
        con.close()

    def test_followed_channel_post_with_ca_wakes_copy(self):   # P25
        d = tempfile.mkdtemp()
        con = tstore.connect(os.path.join(d, "tg.db"))
        tstore.add_candidates(con, ["gems", "other"], "x", NOW)
        post = [{"post": 1, "ts": NOW, "text": f"ape {CA}", "cas": [CA], "tickers": [], "views": 1, "fwd_from": None}]
        hype = os.path.join(d, "hype.db")
        with mock.patch.object(poll, "followed_channels", lambda: {"gems"}), mock.patch.object(copy, "wake") as w:
            tstore.save_posts(con, "gems", post, now=NOW, hype_db=hype)
            w.assert_called_once()
        with mock.patch.object(poll, "followed_channels", lambda: {"gems"}), mock.patch.object(copy, "wake") as w:
            tstore.save_posts(con, "other", post, now=NOW, hype_db=hype)
            w.assert_not_called()
        con.close()


class ProvenWallets(unittest.TestCase):
    def test_bags_make_a_wallet_not_copyable(self):   # P55
        good = {"median_hold_min": 30, "trades_per_day": 5, "bag_share": 0.1}
        self.assertTrue(dokazani.copyable(good, []))
        self.assertFalse(dokazani.copyable(dict(good, bag_share=0.3), []))
        self.assertFalse(dokazani.copyable(dict(good, bag_share=0.6), []))
        self.assertTrue(dokazani.copyable({"median_hold_min": 30, "trades_per_day": 5}, []))   # old stats: no field

    def test_latest_rows_carry_the_bag_count(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wallets.db")
        con = wstore.connect(path)
        dokazani.ensure(con)
        con.execute("INSERT INTO wallets (wallet, first_seen, last_seen, scored_at, stats, labels) VALUES (?,?,?,?,?,?)",
                    ("W", NOW - 86400, NOW, NOW, json.dumps({"median_hold_min": 30, "trades_per_day": 5, "bags": 2, "bag_share": 0.2}), "[]"))
        dokazani.save(con, [{"wallet": "W", "closed_before": 6, "realized_before": 1.0, "win_before": 0.8, "closed_after": 2,
                             "realized_after": 0.5, "win_after": 1.0, "passed": 1}], NOW)
        con.commit()
        con.close()
        rows = dokazani.latest(path)
        self.assertEqual((rows[0]["bags"], rows[0]["bag_share"]), (2, 0.2))


class MintShapeFallback(unittest.TestCase):
    def test_without_base58_the_shape_check_still_works(self):   # P57
        with mock.patch.dict(sys.modules, {"base58": None}):      # import base58 -> ImportError
            self.assertTrue(collect.is_solana_mint(CA))
            self.assertTrue(collect.is_solana_mint("So11111111111111111111111111111111111111112"))
            self.assertFalse(collect.is_solana_mint("x3ea7d1f3a2b4c5d6e7f8091a2b3c4d5e6f7a8b9c0d1e7777"))   # EVM tail
            self.assertFalse(collect.is_solana_mint("0" * 40))
            self.assertEqual(collect.cas_in(f"ape {CA} now"), [CA])
        self.assertTrue(collect.is_solana_mint(CA))                 # with the package: the strict decode


if __name__ == "__main__":
    unittest.main()
