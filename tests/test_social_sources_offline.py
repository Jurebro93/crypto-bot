"""Telegram channels, KOL wallets, convergence and exploration arms, all offline.

    python3 -m unittest tests.test_social_sources_offline
"""
import json
import os
import random
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tg import discover, poll, reader, store as tstore, tgstat  # noqa: E402
from kol import chainwatch, collect, converge, idents, store as kstore  # noqa: E402
from paper import arms  # noqa: E402

CA1 = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
CA2 = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"


def page(channel, posts, public=True, subs="12.5K"):
    head = ('<div class="tgme_channel_info"><div class="tgme_channel_info_header_title"><span>Gem Calls</span></div>'
            f'<span class="counter_value">{subs}</span> <span class="counter_type">subscribers</span></div>') if public else ""
    body = ""
    for pid, iso, text, views, fwd in posts:
        f = (f'<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/{fwd}/9">x</a>') if fwd else ""
        body += (f'<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" '
                 f'data-post="{channel}/{pid}">{f}<div class="tgme_widget_message_text js-message_text" dir="auto">{text}'
                 f'</div><span class="tgme_widget_message_views">{views}</span>'
                 f'<time datetime="{iso}" class="time">x</time></div></div>')
    return head + body


class Reader(unittest.TestCase):
    def test_parse(self):
        p = page("gems", [(5, "2026-10-31T12:00:00+00:00", f"$PEPE CA: {CA1} join t.me/othercalls", "1.2K", None),
                          (6, "2026-10-31T12:05:00+00:00", "gm", "300", "srcchan")])
        info = reader.parse(p, "gems")
        self.assertTrue(info["public"])
        self.assertEqual(info["subs"], 12500)
        self.assertEqual(info["title"], "Gem Calls")
        a, b = info["posts"]
        self.assertEqual(a["cas"], [CA1])
        self.assertEqual(a["tickers"], ["PEPE"])
        self.assertEqual(a["views"], 1200)
        self.assertIn("othercalls", a["links"])
        self.assertEqual(b["fwd_from"], "srcchan")

    def test_channel_names(self):
        self.assertIsNone(reader.channel_name("BonkBot_bot"))
        self.assertIsNone(reader.channel_name("joinchat"))
        self.assertEqual(reader.channel_name("@Sol_Calls"), "sol_calls")
        self.assertEqual(discover.names_in_blob(b'{"url":"https://t.me/alpha_calls","x":"t.me/trunc\\u2026"}'),
                         {"alpha_calls"})


class Channels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "tg.db")
        self.hype = os.path.join(self.tmp, "hype.db")
        self.con = tstore.connect(self.db)
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tg", "config.json")) as f:
            self.cfg = json.load(f)
        self.now = 1_793_000_000

    def iso(self, ts):
        import datetime as dt
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()

    def test_validate_poll_snowball(self):
        tstore.add_candidates(self.con, ["gems", "private1"], "x", self.now - 7200)
        pages = {"gems": page("gems", [(1, self.iso(self.now - 600), f"CA {CA1}", "100", None),
                                       (2, self.iso(self.now - 300), f"next {CA2}", "200", "srcchan")]),
                 "private1": page("private1", [], public=False)}
        read = lambda n: reader.parse(pages[n], n)
        cfg = dict(self.cfg, validate_per_tick=5)
        visited, new = poll.tick(self.con, cfg, {}, self.now, read, sleep=lambda s: None, hype_db=self.hype)
        self.assertEqual(visited, 2)
        st = dict(self.con.execute("SELECT name, status FROM channels"))
        self.assertEqual(st["gems"], "active")
        self.assertEqual(st["private1"], "dead")
        self.assertEqual(st["srcchan"], "candidate")  # found through the forward
        h = sqlite3.connect(self.hype)
        self.assertEqual(h.execute("SELECT COUNT(*) FROM tg_mentions").fetchone()[0], 2)
        # a new post later: only it is stored, and lag is measured
        pages["gems"] = page("gems", [(2, self.iso(self.now - 300), f"next {CA2}", "200", None),
                                      (3, self.iso(self.now + 280), f"again {CA1}", "50", None)])
        poll.visit(self.con, "gems", cfg, self.now + 300, read, self.hype)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM posts WHERE channel='gems'").fetchone()[0], 3)
        self.assertAlmostEqual(self.con.execute("SELECT lag_s FROM channels WHERE name='gems'").fetchone()[0], 20)
        # hot channel (CA in the last hour) is due after 30 s, not 5 min
        self.con.commit()
        _, due = poll.due(self.con, cfg, {}, self.now + 340)
        self.assertIn("gems", due)

    def test_calls_into_kol(self):
        tstore.add_candidates(self.con, ["gems"], "x", self.now)
        self.con.execute("UPDATE channels SET subs=5000, status='active' WHERE name='gems'")
        tstore.save_posts(self.con, "gems", [
            {"post": 1, "ts": self.now, "text": f"ape {CA1}", "cas": [CA1], "tickers": [], "views": 900, "fwd_from": None},
            {"post": 2, "ts": self.now + 5, "text": f"{CA2}", "cas": [CA2], "tickers": [], "views": 10, "fwd_from": "x1"}],
            now=self.now, hype_db=self.hype)
        self.con.commit()
        kcon = kstore.connect(os.path.join(self.tmp, "kol.db"))
        self.assertEqual(collect.from_telegram(kcon, self.db), 2)
        rows = {r[0]: r[1:] for r in kcon.execute("SELECT token, handle, kind, followers, url FROM calls")}
        self.assertEqual(rows[CA1], ("tg:gems", "call", 5000, "https://t.me/gems/1"))
        self.assertEqual(rows[CA2][1], "repost")
        self.assertEqual(collect.from_telegram(kcon, self.db), 0)  # copied once

    def test_tgstat_parse(self):
        resp = {"status": "ok", "response": {"items": [{"id": 1, "date": 100, "views": 5, "link": "t.me/early_calls/77",
                                                        "text": CA1}],
                                             "channels": [{"id": 9, "username": "@early_calls", "participants_count": 900}]}}
        posts, subs = tgstat.parse(resp, CA1)
        self.assertEqual(posts, [("early_calls", 77, 100, CA1, 5)])
        self.assertEqual(subs, {"early_calls": 900})
        r = tgstat.run(self.con, [CA1, CA2], dict(self.cfg["tgstat"], tokens_per_run=1), self.now,
                       search_fn=lambda ca: resp, hype_db=self.hype)
        self.assertEqual(r, (1, 1, 1))


class Wallets(unittest.TestCase):
    def test_kolscan_payload(self):
        rows = [{"wallet_address": "W1", "name": "slingoor", "telegram": "https://t.me/slingdeez",
                 "twitter": "https://x.com/slingoorio", "profit": 10.5, "wins": 3, "losses": 1}]
        payload = json.dumps('5:["$","$L11",null,{"initLeaderboard":' + json.dumps(rows) + '}]')
        html = f'<script>self.__next_f.push([1,{payload}])</script>'
        out = idents.parse_kolscan(html)
        self.assertEqual(out[0]["twitter"], "slingoorio")
        self.assertEqual(out[0]["wallet"], "W1")

    def test_webhook_parse(self):
        tx = {"feePayer": "W1", "signature": "S1", "timestamp": 100, "tokenTransfers": [
            {"mint": chainwatch.SOL, "fromUserAccount": "W1", "toUserAccount": "P", "tokenAmount": 1.5},
            {"mint": CA1, "fromUserAccount": "P", "toUserAccount": "W1", "tokenAmount": 1e6}]}
        self.assertEqual(chainwatch.parse([tx]), [("S1", "W1", CA1, "buy", 100, 1.5)])
        tx2 = {"feePayer": "W1", "signature": "S2", "timestamp": 200, "tokenTransfers": [
            {"mint": CA1, "fromUserAccount": "W1", "toUserAccount": "P", "tokenAmount": 1e6}]}
        self.assertEqual(chainwatch.parse([tx2])[0][3], "sell")

    def test_sync_webhook(self):
        tmp = tempfile.mkdtemp()
        con = kstore.connect(os.path.join(tmp, "kol.db"))
        idents.save(con, [{"wallet": "W1", "name": "a", "twitter": "a", "telegram": None, "pnl": 1, "wins": 1,
                           "losses": 0, "rank": 1}], "kolscan")
        calls = []
        api = lambda m, p="", b=None: calls.append((m, p, b)) or ([] if m == "GET" else {"webhookID": "H1"})
        os.environ["RENDER_EXTERNAL_URL"], os.environ["KOL_HOOK_KEY"] = "https://x.example", "k"
        try:
            self.assertTrue(chainwatch.sync(con, {"max_wallets": 10, "resync_h": 24}, 1000, api, log=lambda *a: None))
            self.assertFalse(chainwatch.sync(con, {"max_wallets": 10, "resync_h": 24}, 2000, api, log=lambda *a: None))
        finally:
            del os.environ["RENDER_EXTERNAL_URL"], os.environ["KOL_HOOK_KEY"]
        self.assertEqual([c[0] for c in calls], ["GET", "POST"])
        self.assertEqual(calls[1][2]["accountAddresses"], ["W1"])


class Converge(unittest.TestCase):
    def test_score(self):
        cfg = converge.DEFAULT
        now = 10_000
        scores = {"goodx": 70, "goodtg": 60, "tg:goodtg": 60, "meh": 10}
        evs = [(CA1, now - 300, "x", "goodx", "call"), (CA1, now - 200, "tg", "tg:goodtg", "call"),
               (CA1, now - 100, "chain", "kolA", "buy"), (CA1, now - 50, "x", "meh", "call")]
        r = converge.score_token(evs, scores, {}, cfg, 50, now)
        self.assertEqual((r["n_x"], r["n_tg"], r["n_chain"], r["n_other"]), (1, 1, 1, 1))
        self.assertEqual(r["platforms"], ["x", "tg", "chain"])
        self.assertEqual(r["score"], 18 + 18 + 22 + 3 + 24)
        sold = converge.score_token(evs + [(CA1, now, "chain", "kolA", "sell")], scores, {}, cfg, 50, now)
        self.assertLess(sold["score"], r["score"] * 0.5)
        promo = [(CA2, now - 100 + i, "tg", f"tg:c{i}", "call") for i in range(6)]
        p = converge.score_token(promo, scores, {}, cfg, 50, now)
        self.assertTrue(p["promo"])


class Arms(unittest.TestCase):
    def test_arm_and_sampling(self):
        c = {"sources": {"telegram", "pumpfun:live"}, "features": {"kol_x": 0.5}}
        self.assertEqual(arms.platforms_of(c, {"platforms": ["chain"]}), ["chain", "pump", "tg", "x"])
        st = {"bad": [0, 30], "good": [20, 5]}
        rng = random.Random(1)
        self.assertTrue(arms.allow("new", st, rng=rng)[0])
        self.assertTrue(all(arms.allow("good", st, rng=rng)[0] for _ in range(20)))
        bad = sum(arms.allow("bad", st, rng=rng)[0] for _ in range(200))
        self.assertLess(bad, 60)   # mostly skipped, never zero chance
        self.assertEqual(arms.loss_reason("stop_loss", 0.01, -0.4, -0.35), "kasni ulaz (odmah pad)")
        self.assertIsNone(arms.loss_reason("trailing", 0.5, 0, 0.2))


class KonvEntry(unittest.TestCase):
    def test_convergence_trade(self):
        import run_paper
        from paper import sim, store
        tmp = tempfile.mkdtemp()
        saved = {k: getattr(run_paper, k) for k in ("DB", "hype_signals", "event_tokens", "market", "rug_verdict",
                                                     "klasa_of", "notify", "t0_of")}
        from learn import weights
        saved_ld = weights.LEARNED_DIR
        saved_conv = kstore.converge
        now = time.time()
        try:
            run_paper.DB = os.path.join(tmp, "paper.db")
            run_paper.hype_signals = lambda now=None: [{"token": "K", "symbol": "K", "ts": now, "score": 15,
                                                        "features": {}, "sources": {"konv"}, "url": None,
                                                        "origin": "hype"}]
            run_paper.event_tokens = lambda c, n=None: []
            run_paper.market = lambda toks: {t: (0.0001, 20_000, 100_000, None) for t in toks}
            run_paper.t0_of = lambda toks, col="t0": {t: "prolaz" for t in toks} if col == "t0" else {}
            from learn import weights
            weights.LEARNED_DIR = tmp
            run_paper.rug_verdict = lambda con, t, cfg, now, paid=True: (None, None, [])
            run_paper.klasa_of = lambda toks: {}
            run_paper.notify = lambda *a, **k: None
            kstore.converge = lambda tokens=None, max_age_min=60, path=None: {"K": {
                "score": 80, "first_ts": now - 120, "platforms": ["x", "tg"], "n_x": 2, "n_tg": 1, "n_chain": 0,
                "kol_selling": 0}}
            opened = run_paper.intake(sim.load_config(), now=now, quiet=True)
            self.assertEqual([c["token"] for c in opened], ["K"])
            con = store.connect(run_paper.DB)
            conf = json.loads(con.execute("SELECT config FROM trades").fetchone()[0])
            self.assertEqual(conf["entry_mode"], "konv")
            self.assertTrue(conf["arm"].startswith("tg+x|"))
            self.assertEqual(conf["tp"][0], [0.4, 0.6])
        finally:
            for k, v in saved.items():
                setattr(run_paper, k, v)
            kstore.converge = saved_conv
            weights.LEARNED_DIR = saved_ld

    def test_skipped_token_reconsidered_when_convergence_grows(self):
        """31.10.: a token first seen with one wallet buy was decided once (skipped) and never looked at again when
        two more KOL wallets bought; now it gets a convergence entry."""
        import run_paper
        from paper import sim, store
        tmp = tempfile.mkdtemp()
        saved = {k: getattr(run_paper, k) for k in ("DB", "hype_signals", "event_tokens", "market", "rug_verdict",
                                                     "klasa_of", "notify", "konv_now", "t0_of")}
        from learn import weights
        saved_ld = weights.LEARNED_DIR
        now = time.time()
        try:
            run_paper.DB = os.path.join(tmp, "paper.db")
            con = store.connect(run_paper.DB)
            store.add_candidate(con, {"token": "W", "ts": now - 600, "origin": "hype", "score": 10,
                                      "decision": "ignored"})
            con.commit()
            con.close()
            run_paper.hype_signals = lambda now=None: [{"token": "W", "symbol": "W", "ts": now, "score": 12,
                                                        "features": {}, "sources": {"konv"}, "url": None,
                                                        "origin": "hype"}]
            run_paper.event_tokens = lambda c, n=None: []
            run_paper.market = lambda toks: {t: (0.0001, 20_000, 100_000, None) for t in toks}
            run_paper.t0_of = lambda toks, col="t0": {t: "prolaz" for t in toks} if col == "t0" else {}
            from learn import weights
            weights.LEARNED_DIR = tmp
            run_paper.rug_verdict = lambda con, t, cfg, now, paid=True: (None, None, [])
            run_paper.klasa_of = lambda toks: {}
            run_paper.notify = lambda *a, **k: None
            run_paper.konv_now = lambda toks, now: {"W": {"score": 68, "first_ts": now - 900, "last_ts": now - 60,
                                                          "platforms": ["chain", "x"], "n_x": 1, "n_tg": 0, "n_chain": 3,
                                                          "kol_selling": 0}} if "W" in toks else {}
            opened = run_paper.intake(sim.load_config(), now=now, quiet=True)
            self.assertEqual([c["token"] for c in opened], ["W"])
        finally:
            for k, v in saved.items():
                setattr(run_paper, k, v)
            weights.LEARNED_DIR = saved_ld

    def test_konv_fresh(self):
        import run_paper
        kc = {"min_score": 55, "max_age_min": 10, "window_min": 30}
        now = 10_000
        self.assertTrue(run_paper.konv_fresh({"score": 68, "first_ts": now - 900, "last_ts": now - 60, "n_x": 1}, kc, now))
        # wallets only, not one post: needs chain_only_min (6) wallets (1.11.: 11 such entries at -100%)
        self.assertFalse(run_paper.konv_fresh({"score": 68, "first_ts": now - 900, "last_ts": now - 60, "n_chain": 4}, kc, now))
        self.assertTrue(run_paper.konv_fresh({"score": 68, "first_ts": now - 900, "last_ts": now - 60, "n_chain": 6}, kc, now))
        self.assertFalse(run_paper.konv_fresh({"score": 68, "first_ts": now - 900, "last_ts": now - 700}, kc, now))
        self.assertFalse(run_paper.konv_fresh({"score": 68, "first_ts": now - 3600, "last_ts": now - 60}, kc, now))
        self.assertFalse(run_paper.konv_fresh({"score": 40, "first_ts": now - 60, "last_ts": now - 60}, kc, now))
        self.assertFalse(run_paper.konv_fresh({"score": 90, "first_ts": now - 60, "last_ts": now, "kol_selling": 1},
                                              kc, now))
        self.assertTrue(run_paper.konv_fresh({"score": 80, "first_ts": now - 120, "n_tg": 1}, kc, now))  # stored copy, no last_ts


if __name__ == "__main__":
    unittest.main()
