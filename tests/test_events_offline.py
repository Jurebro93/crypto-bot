"""events.db (11.11., Jure: one events table, the night batch, unmeasured calls, the EV report, get_hourly_brief,
stale MCP requests): watermarks and the append-only sync, the dual write from the collectors, parity events vs the
old tables over the last 24 h, the backfill's estimate and budget, the health alert inside / outside 08-24 Zagreb,
outcomes and scores, the capped remeasure, the night batch's clock and Helius cap, the EV report and its card on the
Autopilot page (no chip bar), obsolete / expired requests, and get_hourly_brief under 3 s on a synthetic database.
Everything in temp dirs, no network (every fetch is a fake).

    python3 -m unittest tests.test_events_offline
"""
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from events import brief, evreport, health, night, outcomes, remeasure, sources, store  # noqa: E402
from league import copy  # noqa: E402

NOW = int(time.time())
H, DAY = 3600, 86400
TOK = "Hope" + "x" * 36 + "pump"
TOK2 = "Bonk" + "y" * 36 + "pump"
TOK3 = "Wif" + "z" * 37 + "pump"
W1, W2 = "W" * 44, "V" * 44
_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():   # the wallet hooks wake the copy loop; never the repo's own .copy_wake
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


def zagreb(y, m, d, h, mi=0):
    return int(dt.datetime(y, m, d, h, mi, tzinfo=ZoneInfo("Europe/Zagreb")).timestamp())


def _reset_store():
    with store._LOCK:
        store._Q.clear()
        if store._STATE.get("con") is not None:
            try:
                store._STATE["con"].close()
            except sqlite3.Error:
                pass
        store._STATE.update(con=None, con_path=None, path=None, exists_at=0.0, exists=False, fails=0)
    store._TIGHT.update(at=0.0, val=False)


class Env(unittest.TestCase):
    """Every database in a temp dir; events.db exists (start.sh touches it)."""

    def setUp(self):
        from league import store as lstore
        from trade import settings
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.p = {k: os.path.join(d, f"{k}.db") for k in ("events", "kol", "hype", "paper", "scan", "early", "xfeat",
                                                           "league", "trade", "usage", "minute", "rug")}
        env = {"EVENTS_DB": self.p["events"], "KOL_DB": self.p["kol"], "HYPE_DB": self.p["hype"],
               "PAPER_DB": self.p["paper"], "SCAN_DB": self.p["scan"], "EARLY_DB": self.p["early"],
               "XFEAT_DB": self.p["xfeat"], "MINUTE_DB": self.p["minute"], "RUG_DB": self.p["rug"],
               "USAGE_DB": self.p["usage"], "TRADE_OWNER": "Jure", "EVENTS_OFF": ""}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self._saved = (lstore.DB, settings.DB)
        lstore.DB, settings.DB = self.p["league"], self.p["trade"]
        _reset_store()
        open(self.p["events"], "w").close()
        self.econ = store.connect()

    def tearDown(self):
        from league import store as lstore
        from trade import settings
        _reset_store()
        self.econ.close()
        lstore.DB, settings.DB = self._saved
        self.env.stop()
        self.tmp.cleanup()

    # ---- the old tables, as their modules make them -------------------------------------------------------------
    def kol(self):
        from kol import store as kstore
        return kstore.connect(self.p["kol"])

    def hype(self):
        from kol import chainwatch
        con = sqlite3.connect(self.p["hype"])
        chainwatch._create(con)
        con.execute("CREATE TABLE IF NOT EXISTS hype_snapshots (token TEXT, ts INTEGER, price REAL, mcap REAL, "
                    "liquidity REAL, PRIMARY KEY (token, ts))")
        return con

    def events(self, where="1=1", args=()):
        return self.econ.execute(f"SELECT type, mint, actor, source, ts, sol_amount, mcap_usd, payload FROM events "
                                 f"WHERE {where} ORDER BY ts", args).fetchall()


def call(tid, tok, handle, ts, kind="call", source="x"):
    return {"tweet_id": tid, "token": tok, "handle": handle, "ts": ts, "url": "u", "text": "t", "followers": 1000,
            "likes": 0, "retweets": 0, "views": 0, "kind": kind, "match": "ca", "source": source, "symbol": None}


def swap(sig, wallet, mint, ts, sol=0.5, side="buy", slot=None):
    """One Helius enhanced SWAP transaction."""
    tt = ([{"mint": mint, "toUserAccount": wallet, "fromUserAccount": "pool", "tokenAmount": 1000.0}] if side == "buy"
          else [{"mint": mint, "toUserAccount": "pool", "fromUserAccount": wallet, "tokenAmount": 1000.0}])
    nt = ([{"fromUserAccount": wallet, "toUserAccount": "pool", "amount": int(sol * 1e9)}] if side == "buy"
          else [{"fromUserAccount": "pool", "toUserAccount": wallet, "amount": int(sol * 1e9)}])
    return {"feePayer": wallet, "signature": sig, "timestamp": ts, "slot": slot, "type": "SWAP",
            "tokenTransfers": tt, "nativeTransfers": nt}


class Store(Env):
    def test_uid_row_and_insert_never_double(self):
        self.assertEqual(store.uid("call|1|x"), store.uid("call|1|x"))
        self.assertNotEqual(store.uid("call|1|x"), store.uid("call|2|x"))
        self.assertTrue(0 < store.uid("a") < 2 ** 63)
        r = store.row("wallet_buy", NOW, TOK, "helius", W1, 0.5, None, None, key="wallet|S1|" + TOK)
        self.assertEqual(r[0], NOW * 1000)                       # UTC milliseconds
        self.assertEqual(store.row("call", NOW * 1000, TOK)[0], NOW * 1000)
        self.assertEqual(store.insert(self.econ, [r, r]), 1)
        self.assertEqual(store.insert(self.econ, [r]), 0)
        with self.assertRaises(ValueError):
            store.row("nonsense", NOW)
        idx = {r[1] for r in self.econ.execute("PRAGMA index_list(events)")}
        self.assertTrue({"events_mint_ts", "events_actor_ts", "events_type_ts", "events_uid"} <= idx)

    def test_emit_only_into_an_existing_file_and_never_raises(self):
        os.remove(self.p["events"])
        _reset_store()
        self.assertFalse(store.emit("call", NOW, TOK, "x", "ansem", key="k1"))
        self.assertFalse(os.path.exists(self.p["events"]))      # the test suite of other modules writes nothing
        open(self.p["events"], "w").close()
        _reset_store()
        self.econ.close()
        self.econ = store.connect()
        self.assertTrue(store.emit("call", NOW, TOK, "x", "ansem", key="k1"))
        self.assertFalse(store.emit("price_tick", NOW, TOK, mcap=10_000))   # under 30k: not kept
        self.assertEqual(store.flush(), 1)
        # a locked file: the rows stay queued, nothing raises, the next flush writes them
        lock = sqlite3.connect(self.p["events"])
        lock.execute("BEGIN EXCLUSIVE")
        store.emit("call", NOW + 1, TOK, "x", "murad", key="k2")
        with mock.patch("sys.stderr"):
            self.assertEqual(store.flush(timeout=0.1), 0)
        self.assertEqual(len(store._Q), 1)
        lock.rollback()
        lock.close()
        self.assertEqual(store.flush(), 1)
        self.assertEqual(len(self.events("type='call'")), 2)

    def test_retention_and_thinning(self):
        rows = [store.row("call", NOW - 100 * DAY, TOK, "x", "old", key="c-old"),
                store.row("call", NOW - DAY, TOK, "x", "new", key="c-new"),
                store.row("price_tick", NOW - 40 * DAY, TOK, mcap=50_000, key="p-old")]
        base = NOW - 5 * DAY - (NOW - 5 * DAY) % 300
        rows += [store.row("price_tick", base + i * 60, TOK, mcap=50_000, key=f"p{i}") for i in range(10)]
        store.insert(self.econ, rows)
        self.econ.commit()
        out = store.retention(self.econ, NOW, log=lambda *a: None)
        self.assertEqual(out["call"], 1)
        self.assertEqual(out["price_tick"], 1)
        self.assertEqual(out["price_tick (prorijeđeno)"], 8)      # 10 minutes -> one per 5 min
        self.assertEqual(len(self.events("type='price_tick'")), 2)
        sz = store.log_size(self.econ, NOW, log=lambda *a: None)
        self.assertEqual(sz["by_type"], {"call": 1, "price_tick": 2})


    def test_over_budget_cuts_prices_and_transfers_first_then_the_wallet_feed(self):
        rows = []
        for d in (2, 10, 20, 40, 60, 80):
            rows += [store.row("price_tick", NOW - d * DAY, TOK, mcap=50_000, key=f"p{d}"),
                     store.row("transfer", NOW - d * DAY, None, "helius", W1, 2.0, key=f"x{d}"),
                     store.row("wallet_buy", NOW - d * DAY, TOK, "helius", W1, 0.1, key=f"w{d}"),
                     store.row("call", NOW - d * DAY, TOK, "x", "ansem", key=f"c{d}")]
        store.insert(self.econ, rows)
        self.econ.commit()
        lines = []
        with mock.patch.object(store, "MAX_MB", 0.0):
            store.retention(self.econ, NOW, log=lines.append)
        left = dict(self.econ.execute("SELECT type, MIN(ts) FROM events GROUP BY type").fetchall())
        self.assertGreaterEqual(left["price_tick"], (NOW - 7 * DAY) * 1000)
        self.assertGreaterEqual(left["transfer"], (NOW - 7 * DAY) * 1000)
        self.assertGreaterEqual(left["wallet_buy"], (NOW - 30 * DAY) * 1000)
        self.assertEqual(left["call"], (NOW - 80 * DAY) * 1000)        # calls are never cut for room
        self.assertTrue(any("preko budžeta" in ln for ln in lines))

class Watermark(Env):
    def test_sync_reads_only_new_rows_by_rowid(self):
        hc = self.hype()
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)",
                       [(f"S{i}", W1, TOK, "buy", NOW - 600 + i, 0.1) for i in range(5)])
        hc.commit()
        src = next(s for s in sources.sources() if s.name == "chain_trades")
        paths = sources.db_paths()
        self.assertEqual(sources.sync_source(self.econ, src, paths, NOW), (5, 5))
        self.assertEqual(sources.sync_source(self.econ, src, paths, NOW), (0, 0))   # nothing read twice
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)",
                       [(f"T{i}", W2, TOK2, "sell", NOW - 60 + i, None) for i in range(3)])
        hc.commit()
        self.assertEqual(sources.sync_source(self.econ, src, paths, NOW), (3, 3))   # only the 3 new rows read
        wm = store.kv_get(self.econ, "wm:chain_trades")
        self.assertEqual(wm["rowid"], 8)
        self.assertEqual(len(self.events("type='wallet_sell'")), 3)
        # the table rebuilt with fewer rowids (VACUUM): back to the watermark's time, the uid keeps it single
        hc.execute("DELETE FROM chain_trades")
        hc.commit()
        hc.execute("VACUUM")
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)",
                       [("T0", W2, TOK2, "sell", NOW - 60, None), ("U1", W1, TOK3, "buy", NOW + 5, 0.2)])
        hc.commit()
        hc.close()
        n, _ = sources.sync_source(self.econ, src, paths, NOW + 10)
        self.assertEqual(n, 1)
        self.assertEqual(len(self.events("mint=?", (TOK3,))), 1)

    def test_a_new_source_starts_a_day_back_and_closes_follow_the_close_time(self):
        hc = self.hype()
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)",
                       [("OLD", W1, TOK, "buy", NOW - 30 * H, 0.1), ("NEW", W1, TOK, "buy", NOW - 600, 0.1)])
        hc.commit()
        hc.close()
        sources.sync(self.econ, NOW, log=lambda *a: None)
        self.assertEqual(len(self.events("type='wallet_buy'")), 1)   # the backfill covers what is older
        from league import store as lstore
        from trade import settings
        lc = lstore.connect(self.p["league"])
        lc.execute("INSERT INTO trades (user, token, opened_ts, status, size_usd, source, entry_mcap) VALUES "
                   "(?,?,?,?,?,?,?)", (settings.LEAGUE_USER, TOK, NOW - 300, "open", 25, "copy KOL ansem", 60_000))
        lc.execute("INSERT INTO trades (user, token, opened_ts, status) VALUES (?,?,?,?)", ("igrac", TOK, NOW - 300, "open"))
        lc.commit()
        sources.sync(self.econ, NOW, log=lambda *a: None)
        self.assertEqual(len(self.events("type='trade'")), 1)          # only the Autopilot's accounts
        lc.execute("UPDATE trades SET status='closed', closed_ts=?, pnl_usd=5, ret=0.2 WHERE user=?",
                   (NOW - 30, settings.LEAGUE_USER))
        lc.commit()
        lc.close()
        sources.sync(self.econ, NOW, log=lambda *a: None)
        tr = self.events("type='trade'")
        self.assertEqual([json.loads(r[7])["side"] for r in tr], ["buy", "sell"])
        self.assertEqual(json.loads(tr[1][7])["ret"], 0.2)


class DualWrite(Env):
    """The collectors' own writes go into events.db too; a broken events.db never breaks them."""

    def test_calls_wallets_prices_from_the_collectors(self):
        from kol import chainwatch, collect, snap
        from live import store as live_store
        kc = self.kol()
        collect.save(kc, [call("t1", TOK, "ansem", NOW - 100), call("tg:ch/5", TOK, "tg:ch", NOW - 90, source="tg"),
                          call("b1", TOK, "ansem", NOW - 80, kind="brag")])
        kc.commit()
        chainwatch.ingest([swap("S1", W1, TOK, NOW - 70, 0.5, slot=777)], hype_db=self.p["hype"])
        lv = sqlite3.connect(self.p["hype"])
        live_store.mirror_chain(lv, [("S2", TOK2, W2, "buy", 0.3, 1000.0, 1e-6, 50.0, "pool", NOW - 60, None)], {W2})
        lv.commit()
        lv.close()
        n = snap.take(kc, NOW, fetch=lambda toks: [{"baseToken": {"address": TOK, "symbol": "HOPE"}, "priceUsd": "0.001",
                                                    "marketCap": 1_000_000, "liquidity": {"usd": 50_000},
                                                    "pairAddress": "POOL1", "volume": {"h1": 1000}}])
        self.assertEqual(n, 1)
        store.flush()
        ev = {(r[0], r[2] or r[1]): r for r in self.events()}
        self.assertEqual(ev[("call", "ansem")][3], "x")
        self.assertEqual(ev[("call", "tg:ch")][3], "telegram")
        self.assertNotIn(("call", "b1"), ev)                                 # a brag is not a call
        self.assertEqual(len([r for r in self.events("type='call'")]), 2)
        self.assertEqual(ev[("wallet_buy", W1)][5], 0.5)
        self.assertEqual(ev[("wallet_buy", W1)][3], "helius")
        self.assertEqual(ev[("wallet_buy", W2)][3], "pumpportal")
        self.assertEqual(self.econ.execute("SELECT slot FROM events WHERE actor=?", (W1,)).fetchone()[0], 777)
        self.assertEqual(ev[("price_tick", TOK)][6], 1_000_000)
        kc.close()

    def test_a_locked_or_missing_events_db_never_breaks_a_collector(self):
        from kol import chainwatch, collect
        kc = self.kol()
        lock = sqlite3.connect(self.p["events"])
        lock.execute("BEGIN EXCLUSIVE")
        try:
            with mock.patch("sys.stderr"):
                self.assertEqual(collect.save(kc, [call("t9", TOK, "ansem", NOW)]), 1)
                self.assertEqual(chainwatch.ingest([swap("S9", W1, TOK, NOW)], hype_db=self.p["hype"]), 1)
                store.flush(timeout=0.05)
        finally:
            lock.rollback()
            lock.close()
        with mock.patch.object(store, "emit_rows", side_effect=RuntimeError("boom")):
            self.assertEqual(collect.save(kc, [call("t10", TOK, "ansem", NOW)]), 1)
        kc.close()


class Parity(Env):
    """Events vs the old tables for the last 24 h: half written by the collectors' hooks, half straight into the old
    tables (a hook that failed); parity sees the gap and the sync closes it."""

    def test_parity_last_24h(self):
        from kol import chainwatch, collect
        kc = self.kol()
        hc = self.hype()
        for i in range(40):
            ts = NOW - 23 * H + i * 1800
            c = call(f"t{i}", TOK if i % 2 else TOK2, "ansem" if i % 3 else "tg:ch", ts,
                     source="tg" if i % 3 == 0 else "x")
            if i % 2:
                collect.save(kc, [c])
            else:
                kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, source) VALUES (?,?,?,?,?,?)",
                           (c["tweet_id"], c["token"], c["handle"], ts, "call", c["source"]))
            if i % 2:
                chainwatch.ingest([swap(f"S{i}", W1, TOK, ts + 5)], hype_db=self.p["hype"])
            else:
                hc.execute("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", (f"S{i}", W2, TOK2, "sell", ts + 5, None))
            hc.execute("INSERT INTO chain_transfers VALUES (?,?,?,?,?,?)", (f"X{i}", W1, W2, "SOL", 2.0, ts))
            hc.execute("INSERT INTO hype_snapshots VALUES (?,?,?,?,?)", (TOK, ts, 0.001, 80_000, 20_000))
            hc.commit()   # the webhook writes hype.db in its own connection
        kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('old', ?, 'ansem', ?, 'call')",
                   (TOK, NOW - 3 * DAY))
        kc.commit()
        hc.commit()
        store.flush()
        before = sources.parity(24, NOW, self.econ)
        self.assertEqual(before["calls"]["expected"], 40)
        self.assertEqual(before["calls"]["missing"], 20, (before["calls"], len(store._Q), self.events("type='call'")))
        self.assertEqual(before["chain_trades"]["missing"], 20)
        self.assertEqual(before["hype_snapshots"]["missing"], 40)
        out = sources.sync(self.econ, NOW, log=lambda *a: None)
        self.assertTrue(out)
        after = sources.parity(24, NOW, self.econ)
        for name in ("calls", "chain_trades", "chain_transfers", "hype_snapshots"):
            self.assertEqual(after[name]["missing"], 0, name)
            self.assertEqual(after[name]["expected"], 40, name)
        self.assertEqual(after["calls"]["extra"], 0)
        # a post that turned out to be a bot's after it was logged: the source no longer counts it, events still does
        kc.execute("UPDATE calls SET kind='bot' WHERE tweet_id='t1'")
        kc.commit()
        self.assertEqual(sources.parity(24, NOW, self.econ)["calls"]["extra"], 1)
        kc.close()
        hc.close()


class Backfill(Env):
    def _data(self):
        hc = self.hype()
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)",
                       [(f"S{i}", W1, TOK, "buy", NOW - 20 * DAY + i * 3 * H, 0.1) for i in range(160)])
        hc.executemany("INSERT INTO chain_transfers VALUES (?,?,?,?,?,?)",
                       [(f"X{i}", W1, W2, "SOL", 0.1 if i % 2 else 3.0, NOW - 10 * DAY + i * 60) for i in range(100)])
        hc.commit()
        hc.close()

    def test_estimate_first_then_batches_within_14_days(self):
        self._data()
        lines = []
        est = sources.estimate(14, NOW, log=lines.append)
        self.assertEqual(est["chain_trades"]["rows"], sum(1 for i in range(160) if NOW - 20 * DAY + i * 3 * H >= NOW - 14 * DAY))
        self.assertEqual(est["chain_transfers"]["events"], 50)           # SOL transfers under 0.5 are not kept
        self.assertTrue(any("procjena ukupno" in ln for ln in lines))
        with mock.patch.object(sources, "BATCH", 7):
            out = sources.backfill(14, NOW, self.econ, log=lambda *a: None, est=est)
        self.assertEqual(out["chain_trades"], est["chain_trades"]["rows"])
        self.assertEqual(out["chain_transfers"], 50)
        self.assertFalse(self.events("ts < ?", ((NOW - 14 * DAY) * 1000,)))
        self.assertEqual(sources.backfill(14, NOW, self.econ, log=lambda *a: None, est=est)["chain_trades"], 0)
        self.assertTrue(store.kv_get(self.econ, "backfill"))

    def test_budget_skips_what_does_not_fit(self):
        self._data()
        lines = []
        out = sources.backfill(14, NOW, self.econ, log=lines.append, budget_mb=0.001)
        self.assertNotIn("chain_trades", out)
        self.assertTrue(any("preskočen" in ln for ln in lines))


class Health(Env):
    def _feed(self, last_gap_h, types=("call",)):
        rows = []
        for t in types:
            for i in range(7 * 48):
                ts = NOW - 7 * DAY + i * 1800
                if ts <= NOW - last_gap_h * H:
                    rows.append(store.row(t, ts, TOK, "x", "ansem", key=f"{t}{i}"))
        rows += [store.row("signal", NOW - 3 * DAY + i, TOK, "scan", "scan", key=f"s{i}") for i in range(3)]
        store.insert(self.econ, rows)
        self.econ.commit()

    def test_alert_inside_08_24_and_not_outside(self):
        self._feed(3)
        st = health.status(self.econ, NOW)
        call_st = next(s for s in st if s["type"] == "call")
        self.assertTrue(call_st["active"])
        self.assertGreater(call_st["gap_min"], 60)
        self.assertFalse(next(s for s in st if s["type"] == "signal")["active"])   # sparse: never alarms
        day = zagreb(2026, 11, 11, 14)
        night_ = zagreb(2026, 11, 11, 3)
        st_day = [dict(s, gap_min=180.0) if s["type"] == "call" else s for s in st]
        al = health.alerts_for(st_day, day)
        self.assertEqual([a["key"] for a in al], ["events:gap:call"])
        self.assertIn("3.0 h", al[0]["title"])
        self.assertEqual(health.alerts_for(st_day, night_), [])
        self.assertEqual(health.alerts_for(st_day, zagreb(2026, 11, 11, 8, 1))[0]["type"], "call")
        self.assertEqual(health.alerts_for(st_day, zagreb(2026, 11, 11, 7, 59)), [])
        # a feed that is flowing: nothing
        st_ok = [dict(s, gap_min=10.0) if s["type"] == "call" else s for s in st]
        self.assertEqual(health.alerts_for(st_ok, day), [])

    def test_alert_goes_to_usage_alerts_and_the_brief(self):
        self._feed(3)
        lines = []
        with mock.patch.object(health, "in_window", lambda now=None, window=None: True):
            al = health.check(self.econ, NOW, lines.append, usage_db=self.p["usage"])
        self.assertEqual(len(al), 1)
        u = sqlite3.connect(self.p["usage"])
        row = u.execute("SELECT service, level, title FROM alerts WHERE key='events:gap:call'").fetchone()
        u.close()
        self.assertEqual(row[0], "podaci")
        self.assertTrue(any(ln.startswith("UPOZORENJE podaci") for ln in lines))
        self.assertEqual(health.latest(self.econ)["alerts"][0]["type"], "call")

    def test_gaps_from_the_old_table(self):
        hc = self.hype()
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)",
                       [(f"S{i}", W1, TOK, "buy", NOW - 30 * H + i * 600, 0.1) for i in range(30)]
                       + [(f"T{i}", W1, TOK, "buy", NOW - 2 * H + i * 600, 0.1) for i in range(12)])
        hc.commit()
        hc.close()
        g = health.gaps(30, NOW)["wallet_feed"]
        self.assertGreater(g[0][2], 20 * 60)         # ~23 h of silence found


class Outcomes(Env):
    def test_metrics_tp_sl_timeout(self):
        t0 = NOW - 30 * H
        up = [(t0 + i * 60, 1 + i * 0.01, 1 + i * 0.01, 1) for i in range(1, 300)]
        m = outcomes.metrics(up, t0, 1.0, NOW)
        self.assertAlmostEqual(m["ev"], 0.18)
        self.assertAlmostEqual(m["max_1h"], 0.6)
        down = [(t0 + 60, 1.05, 0.65, 0.7), (t0 + 120, 1.5, 1.4, 1.5)]
        self.assertAlmostEqual(outcomes.metrics(down, t0, 1.0, NOW)["ev"], -0.32)
        tie = [(t0 + 60, 1.25, 0.6, 1.0)]
        self.assertAlmostEqual(outcomes.metrics(tie, t0, 1.0, NOW)["ev"], -0.32)   # the stop first in a tie
        flat = [(t0 + i * 600, 1.05, 0.95, 1.03) for i in range(1, 30)]
        m = outcomes.metrics(flat, t0, 1.0, NOW)
        self.assertAlmostEqual(m["ev"], 0.01)
        self.assertAlmostEqual(m["change_4h"], 0.03)
        short = outcomes.metrics(flat[:3], t0, 1.0, t0 + 1800)
        self.assertIsNone(short["max_4h"])

    def _calls(self, ts):
        kc = self.kol()
        kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24, r24h, mcap0) VALUES "
                   "('t1', ?, 'ansem', ?, 'call', 1.5, 0.4, 60000)", (TOK, ts))
        kc.commit()
        kc.close()
        from kol import minute
        mc = minute.connect(self.p["minute"])
        m0 = ts - ts % 60
        candles = [(m0 + i * 60, 1.0 + i * 0.002, 1.0 + i * 0.002 + 0.001, 1.0 + i * 0.002 - 0.001, 1.0 + i * 0.002, 10)
                   for i in range(0, 241)]
        mc.execute("INSERT INTO call_candles VALUES (?,?,?,?,?,?,?)",
                   (TOK, m0, m0 + 240 * 60, len(candles), minute._pack(candles), 1, NOW))
        mc.commit()
        mc.close()

    def test_compute_and_scores_from_measured_calls_only(self):
        ts = NOW - 30 * H
        self._calls(ts)
        rows = [store.row("call", ts, TOK, "x", "ansem", None, 60_000, {"tweet_id": "t1"}, key=f"call|t1|{TOK}"),
                store.row("call", ts + 60, TOK, "x", "ansem", None, None, {"tweet_id": "t1b"}, key="call|t1b"),
                store.row("call", ts, TOK2, "x", "murad", None, None, {"tweet_id": "t2"}, key=f"call|t2|{TOK2}"),
                store.row("call", NOW - 5 * H, TOK2, "telegram", "tg:ch", None, None, {"tweet_id": "t3"}, key="call|t3"),
                store.row("wallet_buy", ts, TOK3, "helius", W1, 0.5, None, None, key="w1")]
        rows += [store.row("price_tick", ts + i * 600, TOK3, "dexscreener", None, None, 100_000 * (1 + i * 0.05),
                           {"p": 1 + i * 0.05}, key=f"p{i}") for i in range(0, 160)]
        store.insert(self.econ, rows)
        self.econ.commit()
        st = outcomes.compute(self.econ, NOW, log=lambda *a: None)
        o = {r[0]: r for r in self.econ.execute("SELECT actor, mint, status, src, max_1h, max_4h, max_24h, change_24h, "
                                                  "ev, reason FROM call_outcomes")}
        self.assertEqual(o["ansem"][2], "ok")
        self.assertIn("minute_candles", o["ansem"][3])
        self.assertIn("kol_measure", o["ansem"][3])
        self.assertEqual(o["ansem"][6], 1.5)                    # 24 h from kol.db's measure
        self.assertAlmostEqual(o["ansem"][4], 0.12, places=2)
        self.assertEqual(o["murad"][2], "unmeasured")           # no data: the night remeasure takes it
        self.assertEqual(o["tg:ch"][2], "pending")
        self.assertEqual(o[W1][2], "ok")
        self.assertEqual(o[W1][3], "price_ticks")
        self.assertAlmostEqual(o[W1][8], 0.18)
        self.assertEqual(st.get("ok"), 3)
        self.assertEqual(store.kv_get(self.econ, "wm:outcomes"), NOW - outcomes.MIN_AGE_S)
        outcomes.scores(self.econ, NOW, log=lambda *a: None)
        sc = {r[1]: r for r in self.econ.execute("SELECT * FROM scores")}
        self.assertEqual(sc["ansem"][2:4], (1, 1))              # the same token the same day = one call
        self.assertEqual(sc["murad"][2:4], (1, 0))              # counted, not measured
        self.assertIsNone(sc["murad"][5])
        self.assertEqual(sc[W1][0], "wallet")
        self.assertEqual(sc["tg:ch"][0], "channel")

    def test_compute_goes_on_next_night_when_its_time_runs_out(self):
        rows = [store.row("wallet_buy", NOW - 40 * H + i * 60, TOK, "helius", W1, 0.1, key=f"w{i}") for i in range(7)]
        store.insert(self.econ, rows)
        self.econ.commit()
        st = outcomes.compute(self.econ, NOW, log=lambda *a: None, chunk=3, budget_s=-1)
        self.assertEqual(sum(st.values()), 3)                           # one chunk, then the time ran out
        st = outcomes.compute(self.econ, NOW, log=lambda *a: None, chunk=3, budget_s=600)
        self.assertEqual(self.econ.execute("SELECT COUNT(*) FROM call_outcomes").fetchone()[0], 7)
        self.assertEqual(store.kv_get(self.econ, "wm:outcomes"), NOW - outcomes.MIN_AGE_S)

    def test_early_wallets(self):
        rows = []
        for i, tok in enumerate((TOK, TOK2, TOK3)):
            t = NOW - (5 + i) * DAY
            rows.append(store.row("call", t, tok, "x", "ansem", key=f"c{i}"))
            rows.append(store.row("wallet_buy", t - 1200, tok, "helius", W1, 0.2, key=f"w{i}"))
            rows.append(store.row("wallet_buy", t + 600, tok, "helius", W2, 0.2, key=f"v{i}"))
            self.econ.execute("INSERT INTO call_outcomes (uid, kind, mint, actor, ts, status, max_4h) VALUES "
                              "(?,?,?,?,?,?,?)", (i, "call", tok, "ansem", t, "ok", 1.5 if i < 2 else 0.1))
        store.insert(self.econ, rows)
        self.econ.commit()
        outcomes.early_wallets(self.econ, NOW, log=lambda *a: None)
        r = self.econ.execute("SELECT wallet, n_early, n_wins, median_lead_min FROM early_wallets").fetchall()
        self.assertEqual(r, [(W1, 3, 2, 20.0)])


class Remeasure(Env):
    def setUp(self):
        super().setUp()
        kc = self.kol()
        self.t_never = NOW - 30 * H
        kc.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,'call')",
                       [("n1", TOK, "fewcalls", self.t_never), ("n2", TOK2, "manycalls", self.t_never + 3600),
                        ("bot1", TOK3, "alertbot", self.t_never)])
        kc.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind, r24h) VALUES (?,?,?,?,'call',0.1)",
                       [(f"m{i}", TOK3, "manycalls", NOW - 2 * DAY - i) for i in range(30)])
        kc.execute("INSERT INTO kols (handle, bot) VALUES ('alertbot', 1)")
        kc.commit()
        kc.close()
        from kol import minute
        mc = minute.connect(self.p["minute"])
        mc.execute("INSERT INTO call_path (tweet_id, token, handle, ts, bad) VALUES ('s1', ?, 'svhandle', ?, 'svijeca')",
                   (TOK3, self.t_never - 600))
        mc.commit()
        mc.close()
        self.req = []

    def fetch(self, pool, end, limit, aggregate=1):
        self.req.append((pool, aggregate))
        if pool == "EMPTY":
            return []
        step = 60 * aggregate
        start = end - limit * step
        px = lambda t: 1.002 ** ((t - self.t_never) / 60)   # noqa: E731 - rises 0.2 % a minute
        return [(t, px(t), px(t + step) * 1.01, px(t) * 0.99, px(t + step), 5)
                for t in range(start - start % step, end, step)]

    def test_never_measured_and_svijeca_measured_within_the_cap(self):
        pools = {TOK: ("P1", 100_000.0), TOK2: ("P2", 100_000.0), TOK3: ("EMPTY", 100_000.0)}
        q = remeasure.queue(sqlite3.connect(self.p["kol"]), sqlite3.connect(self.p["minute"]), self.econ, NOW)
        self.assertEqual([t for t, _ in q][:1], [TOK])           # the caller with few measured calls first
        self.assertNotIn("alertbot", {c[1] for _, cs in q for c in cs})
        self.assertIn("bad:svijeca", {c[3] for _, cs in q for c in cs})
        out = remeasure.run(self.econ, NOW, cap=2, log=lambda *a: None, fetch=self.fetch,
                            fetch_dex=lambda toks: {t: pools[t] for t in toks}, fetch_gt_pool=lambda t: None,
                            fetch_bird=lambda *a: [], force=True)
        self.assertEqual(out["requests"], 2)                      # one token: 1-min + 5-min candles
        self.assertEqual(out["tokens"], 1)
        r = self.econ.execute("SELECT status, src, max_1h, max_24h, ev, mcap0 FROM call_outcomes WHERE tweet_id='n1'"
                              ).fetchone()
        self.assertEqual(r[:2], ("ok", "gt_minute"))
        self.assertGreater(r[2], 0.05)
        self.assertIsNotNone(r[3])
        self.assertAlmostEqual(r[4], 0.18)
        self.assertEqual(remeasure.used(self.econ, NOW), 2)
        out = remeasure.run(self.econ, NOW, cap=10, log=lambda *a: None, fetch=self.fetch,
                            fetch_dex=lambda toks: {t: pools[t] for t in toks}, fetch_gt_pool=lambda t: None,
                            fetch_bird=lambda *a: [], force=True)
        self.assertLessEqual(remeasure.used(self.econ, NOW), 10)
        st = dict(self.econ.execute("SELECT tweet_id, status || ':' || COALESCE(reason, '') FROM call_outcomes"))
        self.assertEqual(st["s1"], "unavailable:nema trgovanja do 30 min nakon poziva")
        self.assertTrue(st["n2"].startswith("ok"))
        self.assertEqual(remeasure.queue(sqlite3.connect(self.p["kol"]), None, self.econ, NOW), [])   # nothing left
        # the night respects its window unless forced
        self.assertEqual(remeasure.run(self.econ, zagreb(2026, 11, 11, 14), log=lambda *a: None)["why"],
                         "izvan noćnog prozora")

    def test_caller_history_shows_the_night_status(self):
        remeasure.run(self.econ, NOW, cap=10, log=lambda *a: None, fetch=self.fetch,
                      fetch_dex=lambda toks: {t: ("P1", 100_000.0) for t in toks}, fetch_gt_pool=lambda t: None,
                      fetch_bird=lambda *a: [], force=True)
        from ui import mcpdata
        mcpdata._CACHE.clear()
        d = mcpdata.caller_history("fewcalls")
        row = next(r for r in d["rows"] if r["token"] == TOK)
        self.assertEqual(row["measure_status"], "ok")
        self.assertEqual(row["measure_source"], "gt_minute")
        self.assertIsNotNone(row["max_1h"])

    def test_cap_leaves_half_of_the_coingecko_day(self):
        from event_calendar import http
        with mock.patch.object(http, "cg_key", lambda: "k"), mock.patch.object(http, "cg_used", lambda today=None: 1400), \
                mock.patch.dict(os.environ, {"CG_DAILY_CALLS": "3000"}):
            self.assertEqual(remeasure.cap_left(self.econ, NOW, 600), 100)


class Night(Env):
    def test_clock(self):
        self.assertEqual(night.due(self.econ, zagreb(2026, 11, 11, 2, 10))[1], "čeka 03:00 (Zagreb)")
        self.assertTrue(night.due(self.econ, zagreb(2026, 11, 11, 3, 5))[0])
        self.assertEqual(night.due(self.econ, zagreb(2026, 11, 11, 14))[1], "izvan noćnog prozora")
        store.kv_put(self.econ, "night_day", "2026-11-11")
        self.assertEqual(night.due(self.econ, zagreb(2026, 11, 11, 4))[1], "noćas je već odrađeno")
        self.assertTrue(night.due(self.econ, zagreb(2026, 11, 12, 3, 30))[0])

    def test_steps_and_the_helius_cap(self):
        from kol import groupdisc
        got = {}

        def fake_night(credits=None, log=print, **kw):
            got["credits"] = credits
            return {"caller_groups": 0}
        lines = []
        with mock.patch.object(groupdisc, "night", fake_night), mock.patch.object(night, "helius_used", lambda *a: 4200.0):
            rep = night.run(zagreb(2026, 11, 11, 3, 5), log=lines.append, econ=self.econ,
                            steps=["outcomes", "scores", "groups", "early", "retention", "size"])
        self.assertEqual(got["credits"], 800)                     # min(3000, 5000 - 4200)
        self.assertEqual(set(rep["steps"]), {"outcomes", "scores", "groups", "early", "retention", "size"})
        self.assertLessEqual(rep["helius_credits"], night.HELIUS_NIGHT_CAP)
        self.assertTrue(any("noćna obrada gotova" in ln for ln in lines))
        # a broken step costs only itself
        with mock.patch.object(outcomes, "scores", side_effect=RuntimeError("x")):
            rep = night.run(zagreb(2026, 11, 11, 3, 5), log=lambda *a: None, econ=self.econ, steps=["scores", "size"])
        self.assertIn("error", rep["steps"]["scores"]["result"])
        self.assertNotIn("error", rep["steps"]["size"]["result"])

    def test_groups_not_run_twice_in_one_night(self):
        from kol import groupdisc
        ec = groupdisc.connect(self.p["early"])
        now = zagreb(2026, 11, 11, 3, 5)
        ec.execute("INSERT INTO group_runs VALUES (?,?,?,?,?)", (now - 3600, "night", 2500, 0, "{}"))
        ec.commit()
        ec.close()
        with mock.patch.object(groupdisc, "night", side_effect=AssertionError("ran twice")):
            r = night.step_groups(now, 5000)
        self.assertEqual((r["ran"], r["credits"]), (False, 2500))


class EvReport(Env):
    def setUp(self):
        super().setUp()
        from league import flags, store as lstore
        from trade import settings
        self.lc = lstore.connect(self.p["league"])
        flags.ensure(self.lc)
        self.tc = settings.connect(self.p["trade"])
        self.settings = settings

    def tearDown(self):
        self.lc.close()
        self.tc.close()
        super().tearDown()

    def _trades(self, user, rets, t0):
        for i, r in enumerate(rets):
            self.lc.execute("INSERT INTO trades (user, token, opened_ts, closed_ts, status, ret, pnl_usd) VALUES "
                            "(?,?,?,?,?,?,?)", (user, f"T{i:02d}" + "x" * 38, t0 + i * 600, t0 + i * 600 + 300,
                                                 "closed", r, r * 25))
        self.lc.commit()

    def test_shadow_skips_paper_proposal_and_the_files(self):
        s = self.settings
        t0 = NOW - 3 * DAY
        rets = [0.3 if i % 2 else -0.3 for i in range(40)]
        self._trades(s.LEAGUE_USER, rets, t0)
        s.put(self.tc, "flag:confluence", {"mode": "shadow", "since": NOW - 5 * DAY})
        for i in range(0, 40, 2):   # the rule would have skipped every losing entry
            self.lc.execute("INSERT INTO shadow_decisions (ts, flag, token, old_action, new_action) VALUES (?,?,?,?,?)",
                            (t0 + i * 600 + 30, "confluence", f"T{i:02d}" + "x" * 38, "ulaz", "preskočeno"))
        s.put(self.tc, "flag:dca_guard", {"mode": "paper", "since": NOW - 5 * DAY})
        self._trades(s.PAPER_USER, [0.1] * 5, t0)
        self.lc.commit()
        out = tempfile.mkdtemp()
        rep = evreport.run(NOW, log=lambda *a: None, econ=self.econ, outdir=out)
        rows = {(r["flag"], r["part"]): r for r in rep["rows"]}
        c = rows[("confluence", "flag")]
        self.assertEqual((c["n"], c["n_outcomes"]), (20, 20))
        self.assertEqual(c["hit_rate"], 0.0)                     # every skipped entry lost
        self.assertEqual(c["ev_pct"], 30.0)                      # the Autopilot without them
        self.assertEqual(c["baseline_ev_pct"], 0.0)
        self.assertEqual(c["delta_ev_pct"], 30.0)
        self.assertIn("shadow → paper", c["proposal"])
        self.assertIn("ručno", c["proposal"])
        p = rows[("dca_guard", "flag")]
        self.assertEqual((p["n"], p["ev_pct"], p["baseline_ev_pct"]), (5, 10.0, 0.0))
        self.assertIsNone(p["proposal"])                         # n < 20
        self.assertEqual(self.econ.execute("SELECT COUNT(*) FROM ev_report").fetchone()[0], len(rep["rows"]))
        files = os.listdir(out)
        self.assertTrue(any(f.endswith(".md") for f in files) and any(f.endswith(".json") for f in files))
        self.assertEqual(evreport.latest(self.econ)["day"], rep["day"])
        # nothing in here changes a flag: proposals are text
        self.assertEqual(s.flag("confluence", con=self.tc), "shadow")

    def test_scanner_and_groups_against_their_baselines(self):
        from kol import groupdisc
        from scan import store as sstore
        s = self.settings
        s.put(self.tc, "flag:market_scan", {"mode": "shadow", "since": NOW - 5 * DAY})
        s.put(self.tc, "flag:group_discovery", {"mode": "shadow", "since": NOW - 5 * DAY})
        sc = sstore.connect(self.p["scan"])
        for i in range(24):
            for src, res in (("caller", -0.05), ("scan", 0.1)):
                sc.execute("INSERT INTO shadow (token, source, stage, found_ts, tradeable, result, hi4h, done) VALUES "
                           "(?,?,?,?,?,?,?,1)", (f"T{i}", src, "migrated", NOW - DAY + i * 600, 1, res, 0.25 if res > 0 else 0.05))
        sc.commit()
        sc.close()
        ec = groupdisc.connect(self.p["early"])
        for i in range(3):
            ec.execute("INSERT INTO group_signals (ts, source, gid, token, ev, hit4h, measured_ts) VALUES (?,?,?,?,?,?,?)",
                       (NOW - DAY + i, "hidden_group", "g1", f"G{i}", 0.18, 1, NOW))
        ec.commit()
        ec.close()
        self.econ.execute("INSERT INTO call_outcomes (uid, kind, ts, status, ev) VALUES (1, 'call', ?, 'ok', -0.1)",
                          (NOW - DAY,))
        rows = {(r["flag"], r["part"]): r for r in evreport.build(NOW, self.econ, log=lambda *a: None)}
        scan_ = rows[("market_scan", "scan:scan")]
        self.assertEqual((scan_["n"], scan_["ev_pct"], scan_["baseline_ev_pct"], scan_["hit_rate"]), (24, 10.0, -5.0, 1.0))
        self.assertIn("shadow → paper", scan_["proposal"])
        self.assertIsNone(rows[("market_scan", "scan:caller")]["proposal"])   # the baseline itself
        g = rows[("group_discovery", "groups:hidden_group")]
        self.assertEqual((g["n"], g["ev_pct"], g["baseline_ev_pct"]), (3, 18.0, -10.0))
        self.assertIsNone(g["proposal"])                                    # n < 20

    def test_summary_drawdown(self):
        s = evreport.summary([0.1, -0.2, -0.1, 0.3])
        self.assertEqual(s["max_dd_pct"], 30.0)
        self.assertEqual(s["hit_rate"], 0.5)
        self.assertEqual(evreport.summary([])["n"], 0)


class Requests(Env):
    """A sell request for a closed position goes to obsolete; a request older than 15 min shows as expired."""

    def test_obsolete_expired_pending(self):
        from trade import executor, settings
        from ui import mcpapi
        tc = executor.connect(self.p["trade"])
        tc.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                   (TOK, NOW - 600, "dry", "open", 0.1))
        tc.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                   (TOK2, NOW - 9000, "dry", "closed", 0.1))
        reqs = [{"id": "g1794340688000", "ts": NOW - 120, "token": TOK2, "side": "sell", "amount": 1, "status": "pending"},
                {"id": "g2", "ts": NOW - 20 * 60, "token": TOK, "side": "buy", "amount": 0.05, "status": "pending"},
                {"id": "g3", "ts": NOW - 60, "token": TOK, "side": "sell", "amount": 0.5, "status": "pending"},
                {"id": "g4", "ts": NOW - 3000, "token": TOK, "side": "buy", "amount": 0.05, "status": "approved"}]
        settings.put(tc, "mcp_requests", reqs)
        self.assertEqual([r["id"] for r in mcpapi.pending(tc, NOW)], ["g3"])
        view = {r["id"]: r["status"] for r in mcpapi.requests_view(tc, NOW)}
        self.assertEqual(view, {"g1794340688000": "obsolete", "g2": "expired", "g3": "pending", "g4": "approved"})
        self.assertEqual(mcpapi.tidy_requests(tc, NOW), 2)
        stored = {r["id"]: (r["status"], r.get("note")) for r in settings.raw(tc)["mcp_requests"]}
        self.assertEqual(stored["g1794340688000"], ("obsolete", "pozicija je već zatvorena"))
        self.assertEqual(stored["g2"][0], "expired")
        self.assertEqual(mcpapi.tidy_requests(tc, NOW), 0)
        tc.close()


from tests.test_pozicije_izlaz_offline import Base as TradeBase  # noqa: E402


class HourlyBrief(TradeBase):
    """get_hourly_brief on a realistic synthetic events.db: one call, every part, under 3 s."""

    def setUp(self):
        super().setUp()
        d = self.tmp.name
        self.p = {k: os.path.join(d, f"{k}.db") for k in ("events", "kol", "hype", "scan", "early", "xfeat", "rug")}
        self.env = mock.patch.dict(os.environ, {"EVENTS_DB": self.p["events"], "KOL_DB": self.p["kol"],
                                                "HYPE_DB": self.p["hype"], "SCAN_DB": self.p["scan"],
                                                "EARLY_DB": self.p["early"], "XFEAT_DB": self.p["xfeat"],
                                                "RUG_DB": self.p["rug"]})
        self.env.start()
        _reset_store()
        econ = store.connect(self.p["events"])
        mints = [f"M{i:03d}" + "q" * 36 + "pump" for i in range(400)]
        wallets = [f"W{i:03d}" + "w" * 40 for i in range(150)]
        rows = []
        for i in range(120_000):   # 14 days: calls, wallet buys, price ticks, signals
            ts = NOW - i * 10   # newest first: the last hour has ~360 events
            m = mints[(i // 10) % len(mints)]   # every mint gets every kind of event
            k = i % 10
            if k < 2:
                rows.append(store.row("call", ts, m, "x" if k else "telegram", f"caller{i % 90}" if k else f"tg:ch{i % 20}",
                                      None, None, {"tweet_id": f"t{i}"}, key=f"c{i}"))
            elif k < 6:
                rows.append(store.row("wallet_buy", ts, m, "helius", wallets[i % len(wallets)], 0.3, key=f"w{i}"))
            elif k < 9:
                rows.append(store.row("price_tick", ts, m, "dexscreener", None, None, 100_000 + i, {"p": 0.0001 + i * 1e-9},
                                      key=f"p{i}"))
            else:
                rows.append(store.row("signal", ts, m, "scan", "scan", None, 90_000, {"stage": "migrated"}, key=f"s{i}"))
        store.insert(econ, rows)
        econ.executemany("INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         [("caller", f"caller{i}", 40, 30, 12, 0.4, 0.25, 0.8, 0.03, NOW, NOW) for i in range(90)])
        econ.executemany("INSERT INTO early_wallets VALUES (?,?,?,?,?,?,?,?)",
                         [(w, 5, 2, 0.4, 12.0, "events", NOW, NOW) for w in wallets[:50]])
        store.kv_put(econ, "health", {"ts": NOW, "alerts": [{"key": "events:gap:wallet_buy", "type": "wallet_buy",
                                                             "title": "Nema događaja"}], "status": []})
        econ.commit()
        econ.close()
        rc = sqlite3.connect(self.p["rug"])
        rc.execute("CREATE TABLE rug_reports (mint TEXT, checked_at INTEGER, symbol TEXT, verdict TEXT, score REAL, "
                   "wash_score REAL, bundle_pct REAL, sniper_pct REAL, cluster_pct REAL, top10_pct REAL, dev TEXT, "
                   "data TEXT, PRIMARY KEY (mint, checked_at))")
        rc.executemany("INSERT INTO rug_reports (mint, checked_at, verdict, sniper_pct, top10_pct) VALUES (?,?,?,?,?)",
                       [(m, NOW - 600, "ok", 4.5, 22.0) for m in mints])
        rc.commit()
        rc.close()
        from scan import store as sstore
        sc = sstore.connect(self.p["scan"])
        sc.executemany("INSERT INTO cand (token, symbol, stage, fees_paid_sol, vol_h1, mcap, checked_ts) VALUES "
                       "(?,?,?,?,?,?,?)", [(m, "SYM", "migrated", 12.5, 40_000, 95_000, NOW - 100) for m in mints])
        sc.commit()
        sc.close()
        from trade import settings
        settings.put(self.con, "mcp_requests", [{"id": "g1", "ts": NOW - 3600, "token": MINT_SELL, "side": "sell",
                                                 "amount": 1, "status": "pending"}])

    def tearDown(self):
        _reset_store()
        self.env.stop()
        super().tearDown()

    def test_one_call_every_part_under_3_s(self):
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(names["get_hourly_brief"]["annotations"]["readOnlyHint"])
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "get_hourly_brief", "arguments": {"limit_signals": 30}}})
        t = time.perf_counter()
        res = json.loads(mcpapi.rpc(body.encode())[1])["result"]
        took = time.perf_counter() - t
        self.assertLess(took, 3.0, res["structuredContent"].get("timing_ms"))
        self.assertFalse(res["isError"])
        d = res["structuredContent"]
        for k in ("portfolio", "trade_requests", "signals", "groups", "range_candidates", "grok_predictions", "health"):
            self.assertIn(k, d)
        self.assertEqual(d["trade_requests"][0]["status"], "obsolete")
        sig = d["signals"]["items"]
        self.assertTrue(0 < len(sig) <= 30)
        f = sig[0]["features"]
        self.assertEqual(f["rug"]["verdict"], "ok")
        self.assertEqual(f["snipers_pct"], 4.5)
        self.assertEqual(f["phase"], "migrated")
        self.assertEqual(f["fees_paid_sol"], 12.5)
        self.assertIsNotNone(f["run_up_since_first_seen_pct"])
        scored = [c for s in sig for c in s["callers"] if c.get("score")]
        self.assertTrue(scored and scored[0]["score"]["n_measured"] == 30)
        self.assertEqual(d["grok_predictions"]["items"], [])
        self.assertIn("note", d["grok_predictions"])
        self.assertEqual(d["health"]["alerts"][0]["type"], "wallet_buy")
        self.assertIn("paper_positions", d["portfolio"])

    def test_since_iso_ms_and_bad_input(self):
        self.assertEqual(brief.parse_since("2026-11-11T08:00:00Z", NOW), 1794384000)
        self.assertEqual(brief.parse_since(1794384000000, NOW), 1794384000)
        self.assertEqual(brief.parse_since("1794384000", NOW), 1794384000)
        self.assertEqual(brief.parse_since(None, NOW), NOW - 3600)
        self.assertIn("error", brief.build("jučer"))
        self.assertIn("error", brief.build(None, "x"))


MINT_SELL = "Sell" + "s" * 36 + "pump"


from tests.test_apui_offline import Base as PageBase, SUMMARY, fake_aplog, fake_equity, history  # noqa: E402


class AutopilotCard(PageBase):
    """The EV report is one closed row under "Još": no new h2, no chip bar, owner only."""

    def setUp(self):
        super().setUp()
        self.ev = os.path.join(self.tmp.name, "events.db")
        self.envp = mock.patch.dict(os.environ, {"EVENTS_DB": self.ev})
        self.envp.start()
        econ = store.connect(self.ev)
        econ.execute("INSERT INTO ev_report VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("2026-11-11", "confluence", "shadow", "flag", 24, 22, 0.1, -12.0, 4.5, 8.0, 1.0, 40, 3.5,
                      "prijedlog: shadow → paper (n=22, EV +3.50 %); odobrava vlasnik ručno", "bilješka", NOW))
        econ.commit()
        econ.close()

    def tearDown(self):
        self.envp.stop()
        super().tearDown()

    def test_card_under_jos_without_a_chip(self):
        from ui import pravitrade
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("EV po značajkama", body)
        card = re.search(r"<details class=ap-sec id=ev-znacajke>.*?</details>", body, re.S)
        self.assertIsNotNone(card)
        self.assertNotIn("<h2", card.group(0))
        self.assertNotIn(" open", card.group(0).split(">")[0])     # closed
        self.assertLess(body.index(">Još<"), body.index("id=ev-znacajke"))
        h2s = re.findall(r"<h2[^>]*>", body)
        self.assertEqual([h for h in h2s if 'data-sec=""' not in h and "nosec" not in h], [])
        self.assertIn("odobrava vlasnik ručno", card.group(0))
        settings_ = __import__("trade.settings", fromlist=["x"])
        settings_.put(self.con, "invited", ["Ivan"])
        self.assertNotIn("EV po značajkama", pravitrade.page({}, "Ivan")[1])


if __name__ == "__main__":
    unittest.main()
