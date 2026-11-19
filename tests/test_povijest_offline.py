"""19.11. (vlasnik: "povijesni profit i gubitak za sve novčanike ... veliki holderi s dužom poviješću ... bundle ... i
najvažnije insajderski novčanici ... što više demo tradeova s praćenjem novčanika"), offline:

  - the history queue: the order of the sources and the skips (relayer, labels, a scored bot, an exchange / pool)
  - the day cap and the wall-clock deadline on a fake clock; a wallet scored within refresh_d is not read again, an
    older one is read incrementally (only since its last stored transaction)
  - the class "veliki holder s dugom poviješću" (value, days held, tier, no exchange, the first_ts never moves later)
  - status() shape; the pass line
  - the members' own history fed back to the pump groups (report only)
  - the demo source of the pump groups and bundles: enters on a watched wallet's buy on its own demo account with the
    fixed source prefix and the MC bucket, the caps, 15-200M first; never a real buy (pause on, caps raised); the
    daily line
  - the social gate keeps the wallet list and the webhook outside its window

    python3 -m unittest tests.test_povijest_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import store as istore  # noqa: E402
from wallets import povijest, store as wstore  # noqa: E402

D = 86400
NOW = 1_795_000_000 // D * D + 10 * 3600


def addr(name):
    return (name + "1" * 44)[:44]


W = {k: addr(k) for k in ("Conf", "Cand", "Kand", "Bund", "R15", "R2", "Rno", "Rel", "Botl", "Hold", "Exch", "Reg",
                          "Fresh", "Old", "Short")}


def world(d):
    p = {"insajderi_db": os.path.join(d, "i.db"), "holderi_db": os.path.join(d, "h.db")}
    ic = istore.connect(p["insajderi_db"])
    ic.execute("INSERT INTO i2_pp (owner, members, cls, confirmed_ts, n_pumps15, n_tokens) VALUES (?,?,?,?,?,?)",
               ("oC", json.dumps([W["Conf"]]), "prije_pumpe", NOW - D, 4, 4))
    ic.execute("INSERT INTO i2_pp (owner, members, cls, confirmed_ts, n_pumps15, n_tokens) VALUES (?,?,?,?,?,?)",
               ("oK", json.dumps([W["Kand"]]), "kandidat", None, 1, 2))
    ic.execute("INSERT INTO i2_pp (owner, members, cls, confirmed_ts, n_pumps15, n_tokens) VALUES (?,?,?,?,?,?)",
               ("oP", json.dumps([W["Cand"]]), "prije_pumpe", None, 2, 3))
    ic.execute("INSERT INTO i2_bundle (bid, members, n_pumps, n_pumps15) VALUES (?,?,?,?)",
               ("p:" + addr("Pay"), json.dumps([W["Bund"]]), 2, 1))
    for eid, tier in (("e15", "pumpa15"), ("e2", "pumpa2")):
        ic.execute("INSERT INTO i2_events (eid, kind, token, t0, tier, win_end) VALUES (?,?,?,?,?,?)",
                   (eid, "jump", addr("T" + eid), NOW - 5 * D, tier, NOW - 5 * D + 3600))
    rows = [("e15", W["R15"], W["R15"], 1, 1), ("e2", W["R2"], W["R2"], 1, 1), ("e15", W["Rno"], W["Rno"], 1, 0),
            ("e15", W["Rel"], "relayer:" + addr("X"), 1, 1), ("e15", W["Botl"], W["Botl"], 1, 1),
            ("e15", W["Exch"], W["Exch"], 1, 1)]
    ic.executemany("INSERT INTO i2_part (eid, wallet, owner, bought_before, sold_into) VALUES (?,?,?,?,?)", rows)
    ic.commit()
    ic.close()
    from holderi import store as hstore
    hc = hstore.connect(p["holderi_db"])
    m15, m2, m1 = addr("Mid15"), addr("Mid2"), addr("Micro")
    for m, mc in ((m15, 50e6), (m2, 5e6), (m1, 1e6)):
        hc.execute("INSERT INTO profile (mint, ts, symbol, mcap, src, data) VALUES (?,?,?,?,?,?)",
                   (m, NOW - 3600, m[:3], mc, "t", "{}"))
    snaps = [(m15, W["Hold"], 0.2, "whale"), (m15, W["Exch"], 5.0, "exchange"), (m2, W["Hold"], 2.0, "whale"),
             (m15, W["Short"], 0.5, "whale"), (m1, W["Hold"], 10.0, "whale")]
    for i, (m, o, pct, cls) in enumerate(snaps):
        hc.execute("INSERT INTO snap VALUES (?,?,?,?,?,?,?,?,?)", (m, NOW - 3600, i + 1, o, None, 1.0, pct, cls, ""))
    hc.execute("INSERT INTO snap VALUES (?,?,?,?,?,?,?,?,?)", (m15, NOW - 40 * D, 2, W["Hold"], None, 1.0, 0.2, "whale", ""))
    hc.execute("INSERT INTO holder_pos (wallet, mint, ts, value_usd, first_ts, pct) VALUES (?,?,?,?,?,?)",
               (W["Short"], m15, NOW, 250_000.0, NOW - 5 * D, 0.5))
    hc.commit()
    hc.close()
    wpath = os.path.join(d, "w.db")
    wc = wstore.connect(wpath)
    wstore.label(wc, W["Botl"], "bot")
    wstore.observe(wc, W["Reg"], "tok", "harvest", "early_buyer", NOW - D)
    for w, ago in ((W["Fresh"], 3), (W["Old"], 10)):
        wc.execute("INSERT OR IGNORE INTO wallets (wallet, first_seen, last_seen, scored_at, last_tx_ts, stats) VALUES "
                   "(?,?,?,?,?,?)", (w, NOW - 30 * D, NOW, NOW - ago * D, NOW - ago * D, json.dumps({"realized_sol": 1})))
    wc.commit()
    return p, wc


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p, self.con = world(self.tmp.name)
        self.c = povijest.config()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_order_skips_and_holders(self):
        info = povijest.holders(self.con, self.c, NOW, self.p["holderi_db"])
        hs = {(r["wallet"], r["tier"]) for r in povijest.holders_list(self.con)}
        self.assertIn((W["Hold"], "15-200M"), hs)               # 50M x 0.2 % = $100k, held 40 days (snap)
        self.assertNotIn((W["Hold"], "2-15M"), hs)              # $100k but seen there only today
        self.assertFalse([w for w, _t in hs if w in (W["Exch"], W["Short"])])   # an exchange; 5 days held
        self.assertEqual(info["n"], 1)
        povijest.build_queue(self.con, self.p, self.c, NOW)
        q = dict(self.con.execute("SELECT wallet, status FROM povijest_queue"))
        order = [w for w, _s in povijest.due(self.con, self.c, NOW)]
        self.assertEqual(order[:7], [W["Conf"], W["Cand"], W["Kand"], W["Bund"], W["R15"], W["R2"], W["Rno"]])
        self.assertEqual(order[7], W["Hold"])
        self.assertIn(W["Reg"], order)
        self.assertNotIn(W["Rel"], q)                                       # a relayer never enters
        self.assertTrue(q[W["Botl"]].startswith("preskočen: oznaka bot"))
        self.assertTrue(q[W["Exch"]].startswith("preskočen: burza"))
        self.assertNotIn(W["Botl"], order)
        # the holder keeps its first_ts when holder_pos later says later (accumulation)
        first = self.con.execute("SELECT first_ts FROM veliki_holderi WHERE wallet=?", (W["Hold"],)).fetchone()[0]
        self.assertEqual(first, NOW - 40 * D)
        md = povijest.holders_md(self.con, info, NOW)
        self.assertIn("# Veliki holderi s dugom poviješću", md)

    def fake_score(self, cost=30, clock=None, step=0.0):
        seen = []

        def score(con, w, pages, method, lookback_d):
            seen.append((w, pages, method, lookback_d))
            if clock is not None:
                clock.t += step
            wstore.log_credits(con, method, cost, w)
            con.execute("UPDATE wallets SET scored_at=?, stats=? WHERE wallet=?",
                        (NOW, json.dumps({"realized_sol": 1.0 if len(seen) % 2 else -1.0}), w))
            return {"closed": 3, "realized_sol": 1.0 if len(seen) % 2 else -1.0}, "C", {}
        return score, seen

    def test_deadline_cap_fresh_and_line(self):
        clk = Clock()
        score, seen = self.fake_score(clock=clk, step=100.0)
        lines = []
        r = povijest.run("day", now=NOW, con=self.con, cfg=self.c, score=score, clock=clk, log=lines.append, **self.p)
        self.assertEqual(r["n"], 3)                                         # 300 s on the fake clock: three wallets
        self.assertTrue(r["cut"])
        self.assertEqual(seen[0], (W["Conf"], 5, "povijest", 90))
        self.assertRegex(lines[0], r"^novčanici povijest: obrađeno 3 \(red \d+: prije pumpe \d+, rani kupci \d+, "
                                   r"holderi \d+\), u plusu 2 od 3 ocijenjenih, Helius 90/60,000, trajanje 300 s; "
                                   r"prekinuto na vremenskoj granici 300 s$")
        done = {w for w, *_x in seen}
        self.assertNotIn(W["Fresh"], done)
        order = [w for w, _s in povijest.due(self.con, self.c, NOW)]
        self.assertNotIn(W["Fresh"], order)                                 # scored 3 days ago: not read again
        self.assertIn(W["Old"], [w for w, _s in povijest.due(self.con, self.c, NOW)] + [W["Old"]])
        # the day cap: 70 credits a wallet worst case; 90 left lets one wallet (30) through, not a second
        score2, seen2 = self.fake_score()
        r2 = povijest.run("night", now=NOW, con=self.con, cfg=dict(self.c, kredita_dan=180), score=score2,
                          clock=Clock(), log=lambda m: None, **self.p)
        self.assertEqual(r2["n"], 1)                                        # 90 used today, 90 left, 70 a wallet
        st = povijest.status(os.path.join(self.tmp.name, "w.db"), NOW)
        self.assertEqual(set(st), {"queue", "skipped", "scored", "scored_povijest", "profitable", "credits_today",
                                   "cap_day", "last", "holders"})
        self.assertEqual(st["credits_today"], 120)
        self.assertEqual(st["last"]["kind"], "night")
        self.assertEqual(set(st["queue"]), set(povijest.SOURCES))
        self.assertGreaterEqual(st["skipped"], 2)

    def test_day_passes_keep_the_night_share(self):
        score, _seen = self.fake_score(cost=10)
        c = dict(self.c, kredita_dan=100, dan_udio=0.4, najvise_stranica=0)   # 20 credits a wallet worst case
        r = povijest.run("day", now=NOW, con=self.con, cfg=c, score=score, clock=Clock(), log=lambda m: None, **self.p)
        self.assertEqual(r["credits"], 30)                                  # 40 % of 100: three wallets of 10

    def test_incremental_refresh_reads_only_new_signatures(self):
        import run_wallets as rw
        from wallets import pnl, rpc
        calls = []

        def swaps(wallet, since_ts=None, max_pages=3, oldest_first=False, on_credits=None, sol_usd=None):
            calls.append((since_ts, max_pages, oldest_first))
            on_credits(10)
            return [], True, None, None
        with mock.patch.object(rpc, "wallet_swaps", swaps), mock.patch.object(pnl, "prices_sol", lambda m, c: ({}, None)):
            rw.score_one(self.con, W["Old"], 5, now=NOW, method="povijest", lookback_d=90)
            rw.score_one(self.con, W["Reg"], 5, now=NOW, method="povijest", lookback_d=90)
        self.assertEqual(calls[0], (NOW - 10 * D, 7, True))               # only what is new since its last tx
        self.assertEqual(calls[1], (NOW - 90 * D, 5, False))              # a first look: 90 days, newest first
        self.assertEqual(self.con.execute("SELECT SUM(credits) FROM helius_credits WHERE method='povijest'").fetchone()[0],
                         20)

    def test_group_history_is_reported_not_a_rule(self):
        from insajderi import prijepumpe
        wpath = os.path.join(self.tmp.name, "w.db")
        self.con.commit()
        h = povijest.group_history([W["Fresh"], W["Old"], W["Conf"]], wpath)
        self.assertEqual((h["n_members"], h["n_scored"], h["realized_sol"], h["profitable_share"]), (3, 2, 2.0, 1.0))
        ic = istore.connect(self.p["insajderi_db"])
        st = {"oC": {"cls": "prije_pumpe", "confirmed": True, "members": [W["Old"]], "pnl_sol": -1.0},
              "oX": {"cls": "kandidat", "confirmed": False, "members": [addr("Nobody")], "pnl_sol": 2.0}}
        with mock.patch.object(wstore, "DB", wpath):
            out = prijepumpe.history(ic, st, NOW)
        self.assertEqual(out, {"groups": 2, "with_history": 1, "agree": 0, "disagree": 1})
        self.assertEqual(ic.execute("SELECT agrees FROM i2_pp_hist WHERE owner='oC'").fetchone()[0], 0)
        ic.close()

    def test_wallet_jobs_outside_the_social_window(self):
        from ops import drustveni, fokus
        import run_kol
        self.assertIn("cmd_chain", run_kol.round_steps(full=False, social=False))
        self.assertIn("cmd_chain", run_kol.round_steps(full=True, social=False))
        self.assertIsNone(drustveni.skip_cmd(["python3", "run_wallets.py", "povijest", "--kind", "night"]))
        self.assertIsNone(fokus.off_key(["python3", "run_wallets.py", "povijest"]))
        self.assertIn("povijest", [k for _m, k, _w in fokus.EXCEPTIONS])
        with open(os.path.join(ROOT, "start.sh")) as f:
            sh = f.read()
        self.assertIn("ops.heavy --night run_wallets.py povijest --kind night", sh)
        self.assertIn("low python3 run_wallets.py povijest --kind day", sh)


# ---------- the demo source ----------------------------------------------------------------------------------------------
from tests.test_pravi_novac_sve_offline import LU, PU, SwitchBase, tok  # noqa: E402


class Demo(SwitchBase):
    def setUp(self):
        super().setUp()
        from insajderi import live as ilive, pp_live
        d = self.tmp.name
        self.idb = os.path.join(d, "insajderi.db")
        self.hdb = os.path.join(d, "hype.db")
        con = istore.connect(self.idb)
        self.wa, self.wb, self.wc = addr("Wa"), addr("Wb"), addr("Wc")
        con.execute("INSERT INTO i2_pp (owner, members, cls, confirmed_ts, n_pumps15, n_tokens) VALUES (?,?,?,?,?,?)",
                    ("O1abcdefgh", json.dumps([self.wa]), "prije_pumpe", 1, 3, 3))
        con.execute("INSERT INTO i2_pp (owner, members, cls, confirmed_ts, n_pumps15, n_tokens) VALUES (?,?,?,?,?,?)",
                    ("K2abcdefgh", json.dumps([self.wc]), "kandidat", None, 1, 2))
        con.execute("INSERT INTO i2_bundle (bid, members, n_pumps, n_pumps15) VALUES (?,?,?,?)",
                    ("p:Pay123456789", json.dumps([self.wb]), 2, 1))
        con.commit()
        con.close()
        hc = sqlite3.connect(self.hdb)
        hc.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, "
                   "PRIMARY KEY (sig, mint))")
        hc.commit()
        hc.close()
        p = mock.patch.dict(os.environ, {"INSAJDERI_DB": self.idb, "HYPE_DB": self.hdb})
        p.start()
        self.addCleanup(p.stop)
        pp_live._WATCH.update(ts=0.0, v=[])
        pp_live._TRIED.clear()
        pp_live._LAST.clear()
        pp_live._LAST["ts"] = 0.0
        ilive._WATCH.update(ts=0.0, v=[])
        self.flag("insajderi2", "paper")
        self.pp = pp_live

    def chain(self, sig, w, t, side, ts):
        hc = sqlite3.connect(self.hdb)
        hc.execute("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", (sig, w, t, side, int(ts), 1.0))
        hc.commit()
        hc.close()

    def go(self, mcap=20e6, now=None, cfg=None):
        row = (self.quote["row"][0], 300_000.0, None, mcap, "SYM", {"m5": 1.0})
        mk = lambda toks: {x: row for x in toks}   # noqa: E731
        self.pp._WATCH.update(ts=0.0, v=[])
        real = istore.config
        with open(os.path.join(ROOT, "insajderi", "config.json"), encoding="utf-8") as f:
            base = json.load(f)
        with mock.patch.object(istore, "config", lambda *_a, **_k: real({**base, **(cfg or {})})):
            return self.pp.run_once(self.lg, market_fn=mk, now=now or self.now, sol=150.0, force=True)

    def test_enters_tags_caps_and_never_real(self):
        from trade import executor, settings
        settings.pauza_set(self.con, True, "test", "pauza")
        boom = mock.patch.object(executor, "buy", side_effect=AssertionError("no real buy from the demo source"))
        boom.start()
        self.addCleanup(boom.stop)
        self.chain("s1", self.wa, tok(1), "buy", self.now - 20)
        self.chain("s2", self.wb, tok(2), "buy", self.now - 10)
        with mock.patch("builtins.print") as pr:
            got = self.go()
        self.assertEqual(sorted(u for u, _t in got), [self.pp.USER, self.pp.USER], pr.call_args_list)
        rows = {r[0]: r[1:] for r in self.lg.execute("SELECT token, user, kind, mc_bucket FROM pp_trades")}
        self.assertEqual(rows[tok(1)], (self.pp.USER, "prije_pumpe", "15-200M"))
        self.assertEqual(rows[tok(2)], (self.pp.USER, "bundle", "15-200M"))
        srcs = dict(self.lg.execute("SELECT token, source FROM trades WHERE user=?", (self.pp.USER,)))
        self.assertTrue(srcs[tok(1)].startswith("prije pumpe: O1abcd ("), srcs)
        self.assertTrue(srcs[tok(2)].startswith("bundle: Pay123 ("), srcs)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE user IN (?, ?)", (LU, PU)).fetchone()[0], 0)
        # a candidate's buy of a 5M token: 2-15M is let in while under 60 % of the caps
        self.chain("s3", self.wc, tok(3), "buy", self.now - 5)
        self.go(mcap=5e6)
        r = self.lg.execute("SELECT kind, mc_bucket FROM pp_trades WHERE token=?", (tok(3),)).fetchone()
        self.assertEqual(tuple(r), ("prije_pumpe_kandidat", "2-15M"))
        self.assertTrue(self.lg.execute("SELECT source FROM trades WHERE token=?", (tok(3),)).fetchone()[0]
                        .startswith("prije pumpe kandidat: K2abcd"))
        # caps: with max 4 open, a 2-15M buy is refused at 3 open (60 %), a 15M+ one still enters
        self.chain("s4", self.wa, tok(4), "buy", self.now - 4)
        self.go(mcap=5e6, cfg={"pp_demo_max_open": 4})
        self.assertIsNone(self.lg.execute("SELECT 1 FROM pp_trades WHERE token=?", (tok(4),)).fetchone())
        self.chain("s5", self.wa, tok(5), "buy", self.now - 3)
        self.go(mcap=30e6, cfg={"pp_demo_max_open": 4})
        self.assertIsNotNone(self.lg.execute("SELECT 1 FROM pp_trades WHERE token=?", (tok(5),)).fetchone())
        self.chain("s6", self.wa, tok(6), "buy", self.now - 2)
        self.go(mcap=30e6, cfg={"pp_demo_max_open": 4})
        self.assertIsNone(self.lg.execute("SELECT 1 FROM pp_trades WHERE token=?", (tok(6),)).fetchone())   # 4 open
        # the group sells: the demo row closes; the daily line
        self.chain("s7", self.wa, tok(1), "sell", self.now + 30)
        self.go(now=self.now + 60)
        st = self.lg.execute("SELECT status, exit_reason FROM pp_trades WHERE token=?", (tok(1),)).fetchone()
        self.assertEqual(tuple(st), ("closed", "wallet_sold"))
        ln = self.pp.line(self.lg, self.now + 60)
        self.assertTrue(ln.startswith("demo praćenje novčanika: otvoreno 3, danas zatvoreno 1; prije pumpe 15-200M: "
                                      "n=1, srednje "), ln)
        for part in ("; 2-15M: n=0", "; bundle: n=0", "; kopija dokazanih: n=0", "; insajderi2: n=0",
                     "nikad ispod 3 %"):
            self.assertIn(part, ln)
        self.assertIn("insajderi2", settings.NEVER_LIVE)

    def test_old_rows_on_the_paper_account_still_exit_and_count(self):
        from insajderi import live as ilive
        from league import store as lstore
        from wallets import kopija_demo
        self.assertEqual(kopija_demo.demo_user(), self.pp.USER)
        self.assertEqual(lstore.account(self.lg, self.pp.USER)["start"], 5000.0)   # the bot account's own start
        self.assertEqual(lstore.account(self.lg, PU)["start"], lstore.START_USD)   # everyone else: unchanged
        kopija_demo.ensure(self.lg)
        ilive.ensure(self.lg)
        px = self.quote["row"][0]
        t1 = lstore.buy(self.lg, PU, tok(11), "K", 15.0, px, 300_000.0, "kopija dokazanih: stara", None, 20e6)
        t2 = lstore.buy(self.lg, PU, tok(12), "I", 15.0, px, 300_000.0, "insajderi2: grupa O9", None, 20e6)
        self.lg.execute("INSERT INTO kopija_trades (user, token, wallet, buy_ts, opened_ts, trade_id, size_usd, status) "
                        "VALUES (?,?,?,?,?,?,?,'open')", (PU, tok(11), self.wa, int(self.now) - 100, int(self.now) - 90,
                                                          t1, 15.0))
        self.lg.execute("INSERT INTO insajderi2_trades (user, token, owner, wallet, buy_ts, opened_ts, trade_id, size_usd, "
                        "status) VALUES (?,?,?,?,?,?,?,?,'open')", (PU, tok(12), "O9", self.wb, int(self.now) - 100,
                                                                     int(self.now) - 90, t2, 15.0))
        self.lg.commit()
        con = istore.connect(self.idb)
        con.execute("INSERT INTO i2_groups (owner, members, cls, confirmed_ts, score) VALUES (?,?,?,?,?)",
                    ("O9", json.dumps([self.wb]), "insajder", 1, 9))
        con.commit()
        con.close()
        ilive._WATCH.update(ts=0.0, v=[])
        self.chain("x1", self.wa, tok(11), "sell", self.now - 10)
        self.chain("x2", self.wb, tok(12), "sell", self.now - 10)
        row = (px, 300_000.0, None, 20e6, "SYM", {"m5": 1.0})
        mk = lambda toks: {x: row for x in toks}   # noqa: E731
        kopija_demo.exits(self.lg, mk, self.hdb, self.now)
        kopija_demo.sync_closed(self.lg)
        ilive.exits(self.lg, mk, self.hdb)
        ilive.sync_closed(self.lg)
        for table, t in (("kopija_trades", tok(11)), ("insajderi2_trades", tok(12))):
            r = self.lg.execute(f"SELECT user, status, exit_reason FROM {table} WHERE token=?", (t,)).fetchone()
            self.assertEqual(tuple(r), (PU, "closed", "wallet_sold"), table)    # exited on its own account
        self.assertEqual(kopija_demo.stats(self.lg, self.now)["n"], 1)          # both accounts are counted
        self.assertEqual(ilive.demo_stats(self.lg)["n"], 1)

    def test_midcap_guards_from_2m(self):
        from wallets import kopija_demo
        px = self.quote["row"][0]
        self.assertIsNone(kopija_demo.guards(tok(20), (px, 60_000.0, None, 3e6, "S", {})))     # 2 % of MC, 3M: in
        self.assertIn("likvidnost samo", kopija_demo.guards(tok(21), (px, 20_000.0, None, 1e6, "S", {})))   # 1M: as before
        self.assertIsNotNone(kopija_demo.guards(tok(22), (px, 9_000.0, None, 3e6, "S", {})))   # under 15k: never

    def test_webhook_order_and_off(self):
        from insajderi import live as ilive
        self.assertEqual(ilive.webhook_wallets()[:3], [self.wa, self.wb, self.wc])   # confirmed, bundle, candidate
        self.flag("insajderi2", "off")
        self.assertEqual(ilive.webhook_wallets(), [])
        self.chain("s1", self.wa, tok(1), "buy", self.now - 20)
        self.assertEqual(self.go(), [])

    def test_caps_raised(self):
        from wallets import kopija_demo
        c = istore.config()
        self.assertEqual((c["demo_max_open"], c["demo_per_day"], c["pp_demo_max_open"], c["pp_demo_per_day"],
                          c["max_webhook"]), (30, 150, 40, 200, 135))
        self.assertEqual((kopija_demo.MAX_OPEN, kopija_demo.PER_DAY), (40, 200))
        with open(os.path.join(ROOT, "wallets", "config.json")) as f:
            pv = json.load(f)["povijest"]
        self.assertEqual((pv["kredita_dan"], pv["najvise_stranica"], pv["pass_max_s"]),
                         (60000, 5, {"day": 300, "night": 3600}))


if __name__ == "__main__":
    unittest.main()
